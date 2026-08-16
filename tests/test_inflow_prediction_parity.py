"""Python/브라우저 수신 예측엔진의 수치 parity 계약."""

from __future__ import annotations

import builtins
import json
import math
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from rate_monitor.services.inflow_prediction_service import predict_range
from tests.strategy_output_helper import built_strategy_html

ROOT = Path(__file__).resolve().parents[1]
VECTOR_FILE = ROOT / "tests" / "data" / "inflow_parity_vectors.json"
REL_TOLERANCE = 1e-9
ABS_TOLERANCE = 1e-12
SCENARIO_FIELDS = (
    "predicted_new_money",
    "predicted_rollover_rate_pct",
    "predicted_total",
    "surface_interest_delta",
)


def _load_vectors() -> list[dict]:
    payload = json.loads(VECTOR_FILE.read_text(encoding="utf-8"))
    vectors = payload.get("vectors")
    assert isinstance(vectors, list) and vectors, "parity golden vector가 비어 있습니다"
    return vectors


def _identity_round(number, ndigits=None):
    del ndigits
    return number


def _predict_range_raw(inputs: dict) -> dict:
    # production 엔진은 공개 결과를 반올림한다. §5.2 parity 계약은 반올림 전 값을
    # 요구하므로 읽기 전용 엔진 코드는 건드리지 않고 테스트 호출에서만 round를
    # identity로 바꿔 같은 계산 경로의 원값을 관측한다.
    with patch.object(builtins, "round", side_effect=_identity_round):
        return predict_range(**inputs)


def _assert_close(actual: float, expected: float, *, context: str) -> None:
    assert math.isclose(
        float(actual),
        float(expected),
        rel_tol=REL_TOLERANCE,
        abs_tol=ABS_TOLERANCE,
    ), f"{context}: actual={actual!r} expected={expected!r}"


def _assert_contract(actual: dict, expected: dict, *, context: str) -> None:
    for scenario_key in ("low", "base", "high"):
        actual_scenario = actual["scenarios"][scenario_key]
        expected_scenario = expected["scenarios"][scenario_key]
        for field in SCENARIO_FIELDS:
            _assert_close(
                actual_scenario[field],
                expected_scenario[field],
                context=f"{context}.{scenario_key}.{field}",
            )

    for bound in ("min", "max"):
        _assert_close(
            actual["predicted_total_range"][bound],
            expected["predicted_total_range"][bound],
            context=f"{context}.predicted_total_range.{bound}",
        )


def _extract_js_function(html: str, name: str) -> str:
    marker = f"function {name}("
    start = html.find(marker)
    assert start >= 0, f"빌드 산출 HTML에서 JS 함수 marker를 찾지 못했습니다: {name}"

    signature_opening = html.find("(", start)
    paren_depth = 0
    quote: str | None = None
    escaped = False
    opening = -1
    for position in range(signature_opening, len(html)):
        char = html[position]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in {'"', "'", "`"}:
            quote = char
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
            if paren_depth == 0:
                opening = html.find("{", position + 1)
                break

    assert opening >= 0, f"JS 함수 본문 여는 중괄호를 찾지 못했습니다: {name}"

    depth = 0
    quote = None
    escaped = False
    for position in range(opening, len(html)):
        char = html[position]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in {'"', "'", "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return html[start : position + 1]

    raise AssertionError(f"JS 함수 닫는 중괄호를 찾지 못했습니다: {name}")


def _extract_inflow_model(html: str) -> dict:
    marker = '<script id="rate-monitor-data" type="application/json">'
    start = html.find(marker)
    assert start >= 0, "빌드 산출 HTML에서 rate-monitor-data를 찾지 못했습니다"
    start += len(marker)
    end = html.find("</script>", start)
    assert end >= 0, "빌드 산출 HTML의 rate-monitor-data 종료 marker가 없습니다"

    payload = json.loads(html[start:end].replace("<\\/", "</"))
    model = payload.get("strategy", {}).get("inflow_prediction")
    assert isinstance(model, dict), "빌드 산출 HTML에 inflow_prediction 설정이 없습니다"
    return model


def _node_vector_args(vectors: list[dict]) -> list[dict]:
    converted = []
    for vector in vectors:
        inputs = vector["inputs"]
        converted.append(
            {
                "name": vector["name"],
                "args": {
                    "baseline": inputs["baseline_new_money"],
                    "maturity": inputs["maturity_amount"],
                    "rollover": inputs["current_rollover_rate_pct"],
                    "ownRate": inputs["current_own_rate"],
                    "proposed": inputs["proposed_rate"],
                    "top10": inputs["market_top10_rate"],
                    "term": inputs["term_months"],
                },
            }
        )
    return converted


def _run_ui_functions_in_node(vectors: list[dict]) -> list[dict]:
    node = shutil.which("node")
    assert node is not None, "Stage C parity 검증에는 node 실행환경이 필수입니다"

    html = built_strategy_html()
    functions = [
        _extract_js_function(html, name)
        for name in ("logistic", "runInflowScenario", "predictInflow")
    ]
    model_json = json.dumps(_extract_inflow_model(html), ensure_ascii=False, separators=(",", ":"))
    vectors_json = json.dumps(
        _node_vector_args(vectors),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    script = "\n".join(
        [
            '"use strict";',
            f"const INFLOW_MODEL={model_json};",
            *functions,
            f"const vectors={vectors_json};",
            """
const results=vectors.map(vector=>{
  const args=vector.args;
  const scenarios={};
  for(const scenario of INFLOW_MODEL.scenarios){
    const raw=runInflowScenario({...args,scenario});
    scenarios[scenario.key]={
      predicted_new_money:raw.newMoney,
      predicted_rollover_rate_pct:raw.p1*100,
      predicted_total:raw.total,
      surface_interest_delta:raw.cost
    };
  }
  const summary=predictInflow(args);
  return {
    name:vector.name,
    actual:{
      scenarios,
      predicted_total_range:{min:summary.minTotal,max:summary.maxTotal}
    }
  };
});
process.stdout.write(JSON.stringify({vectors:results}));
""".strip(),
        ]
    )
    completed = subprocess.run(
        [node, "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, (
        "Node parity harness 실행 실패\n"
        f"stdout={completed.stdout}\n"
        f"stderr={completed.stderr}"
    )
    payload = json.loads(completed.stdout)
    results = payload.get("vectors")
    assert isinstance(results, list), "Node parity 결과 형식이 올바르지 않습니다"
    return results


def test_python_predict_range_matches_frozen_golden_vectors() -> None:
    for vector in _load_vectors():
        actual = _predict_range_raw(vector["inputs"])
        _assert_contract(
            actual,
            vector["expected"],
            context=f"python.{vector['name']}",
        )


def test_built_ui_javascript_matches_python_and_golden_vectors() -> None:
    vectors = _load_vectors()
    golden_by_name = {vector["name"]: vector for vector in vectors}
    python_by_name = {
        vector["name"]: _predict_range_raw(vector["inputs"])
        for vector in vectors
    }

    for js_result in _run_ui_functions_in_node(vectors):
        name = js_result["name"]
        assert name in golden_by_name, f"알 수 없는 JS parity vector: {name}"
        actual = js_result["actual"]
        _assert_contract(
            actual,
            golden_by_name[name]["expected"],
            context=f"javascript.{name}",
        )
        _assert_contract(
            actual,
            python_by_name[name],
            context=f"python-js.{name}",
        )


def test_js_extractor_fails_closed_when_marker_is_absent() -> None:
    with pytest.raises(AssertionError, match="predictInflow"):
        _extract_js_function("function logistic(x){return x}", "predictInflow")
