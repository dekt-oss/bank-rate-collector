from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from rate_monitor.services.public_structural_v2_forecast_provider import (
    PublicForecastRequest,
    resolve_public_forecast,
)
from rate_monitor.services.public_structural_v2_inflow_service import public_structural_v2_config

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "public-structural-v2"


def _request() -> PublicForecastRequest:
    return PublicForecastRequest(
        generated_at="2026-08-23T09:00:00+09:00",
        candidate_rates=(3.50, 3.55, 3.60),
        baseline_new_money=100.0,
        maturity_amount=200.0,
        current_rollover_rate_pct=60.0,
        current_own_rate=3.50,
        term_months=12,
    )


def _request_dict(request: PublicForecastRequest) -> dict:
    return {
        "generated_at": request.generated_at,
        "candidate_rates": list(request.candidate_rates),
        "baseline_new_money": request.baseline_new_money,
        "maturity_amount": request.maturity_amount,
        "current_rollover_rate_pct": request.current_rollover_rate_pct,
        "current_own_rate": request.current_own_rate,
        "term_months": request.term_months,
    }


def _node(script_lines: list[str]) -> dict | list:
    node = shutil.which("node")
    assert node is not None, "Stage H parity에는 node가 필요합니다"
    sources = [
        (WEB / "inflow_engine.js").read_text(encoding="utf-8"),
        (WEB / "decision_contract.js").read_text(encoding="utf-8"),
        (WEB / "forecast_provider.js").read_text(encoding="utf-8"),
        *script_lines,
    ]
    completed = subprocess.run(
        [node, "-e", "\n".join(sources)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_structural_provider_js_matches_python_exact_payload() -> None:
    request = _request()
    expected = resolve_public_forecast(request=request)
    request_json = json.dumps(_request_dict(request), ensure_ascii=False)
    config_json = json.dumps(public_structural_v2_config(), ensure_ascii=False)

    actual = _node(
        [
            f"const request={request_json};",
            f"const inflowConfig={config_json};",
            (
                "const provider=PublicStructuralV2ForecastProvider.createStructuralProvider("
                "PublicStructuralV2DecisionContract,PublicStructuralV2Inflow,inflowConfig);"
            ),
            (
                "const out=PublicStructuralV2ForecastProvider.validatePublicForecast("
                "provider(request),request);"
            ),
            "process.stdout.write(JSON.stringify(out));",
        ]
    )

    assert actual == expected


def test_js_async_provider_and_unavailable_contract() -> None:
    request = _request()
    request_json = json.dumps(_request_dict(request), ensure_ascii=False)
    payload = resolve_public_forecast(request=request)
    payload_json = json.dumps(payload, ensure_ascii=False)

    actual = _node(
        [
            f"const request={request_json};",
            f"const payload={payload_json};",
            "(async()=>{",
            (
                "const ready=await PublicStructuralV2ForecastProvider.resolveForecast("
                "request,async()=>payload);"
            ),
            (
                "const unavailable=await PublicStructuralV2ForecastProvider.resolveForecast("
                "request,async()=>{throw new "
                "PublicStructuralV2ForecastProvider.ProviderUnavailableError();});"
            ),
            "process.stdout.write(JSON.stringify({ready,unavailable}));",
            "})().catch(error=>{console.error(error);process.exit(1);});",
        ]
    )

    assert actual["ready"] == payload
    assert actual["unavailable"]["status"] == "unavailable"
    assert actual["unavailable"]["scenarios"] == []


def test_js_rejects_private_metadata_and_rate_axis_drift() -> None:
    request = _request()
    request_json = json.dumps(_request_dict(request), ensure_ascii=False)
    payload = resolve_public_forecast(request=request)
    payload_json = json.dumps(payload, ensure_ascii=False)

    actual = _node(
        [
            f"const request={request_json};",
            f"const clean={payload_json};",
            "const cases=[",
            "  {...clean,private_model:'confidential-v9'},",
            (
                "  {...clean,scenarios:clean.scenarios.map((row,index)=>"
                "index?row:{...row,training_metric:.91})},"
            ),
            "  {...clean,scenarios:clean.scenarios.slice(0,-1)}",
            "];",
            (
                "const out=cases.map(payload=>{try{"
                "PublicStructuralV2ForecastProvider.validatePublicForecast(payload,request);"
                "return 'accepted';}catch(error){return String(error.message||error);}});"
            ),
            "process.stdout.write(JSON.stringify(out));",
        ]
    )

    assert actual[0] == "public_forecast:unknown_fields:private_model"
    assert "unknown_fields:training_metric" in actual[1]
    assert actual[2] == "forecast_provider:scenario_rate_axis_mismatch"


def test_js_component_tolerance_matches_python_large_amount_semantics() -> None:
    request = PublicForecastRequest(
        generated_at="2026-08-23T09:00:00+09:00",
        candidate_rates=(3.50,),
        baseline_new_money=1.0,
        maturity_amount=1.0,
        current_rollover_rate_pct=50.0,
        current_own_rate=3.50,
        term_months=12,
    )
    payload = {
        "version": "inflow-public-forecast-v1",
        "generated_at": request.generated_at,
        "status": "ready",
        "amount_unit": "KRW_100M",
        "rate_unit": "percent",
        "scenarios": [
            {
                "rate_pct": 3.50,
                "predicted_new_money": 1_000_000_000.0,
                "predicted_rollover": 1_000_000_000.0,
                "predicted_total": 2_000_000_001.0,
                "incremental_total": 0.0,
                "surface_interest_delta": 0.0,
            }
        ],
    }
    expected = resolve_public_forecast(request=request, provider=lambda req: payload)

    actual = _node(
        [
            f"const request={json.dumps(_request_dict(request))};",
            f"const payload={json.dumps(payload)};",
            (
                "const out=PublicStructuralV2ForecastProvider.validatePublicForecast("
                "payload,request);"
            ),
            "process.stdout.write(JSON.stringify(out));",
        ]
    )

    assert actual == expected
