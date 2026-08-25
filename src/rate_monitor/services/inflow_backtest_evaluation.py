"""수신예측 challenger를 동일 기준으로 평가하는 데이터 독립 backtest evaluator.

실제 내부자료나 모델 artifact를 저장하지 않는다. Private runtime에서 생성한 OOS 예측과
실제값을 같은 metric 정의로 점수화하기 위한 순수 계산 계약이다. 이 모듈의 synthetic
테스트를 public repository에서 실행할 수 있지만 실제 내부 row/점수는 public CI에 올리지
않는다.
"""

from __future__ import annotations

import math
from typing import Any

EVALUATOR_VERSION = "inflow-backtest-evaluator-v1"
_DIRECTION_TOLERANCE = 1e-9
_AMOUNT_TOLERANCE = 1e-9

_REQUIRED_FIELDS = frozenset(
    {
        "actual_new_money",
        "predicted_new_money",
        "actual_rollover",
        "predicted_rollover",
        "maturity_amount",
        "pricing_event",
    }
)
_ALLOWED_FIELDS = _REQUIRED_FIELDS | {"baseline_total"}


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field}:must_be_finite_number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}:must_be_finite_number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field}:must_be_finite_number")
    return parsed


def _direction(value: float) -> int:
    if value > _DIRECTION_TOLERANCE:
        return 1
    if value < -_DIRECTION_TOLERANCE:
        return -1
    return 0


def validate_backtest_record(row: Any, *, index: int = 0) -> dict[str, float | bool | None]:
    """한 OOS prediction row의 수치 invariant와 event 기준점을 검증한다."""
    if not isinstance(row, dict):
        raise ValueError(f"row_{index}:must_be_object")

    unknown = sorted(set(row) - _ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"row_{index}:unknown_fields:{','.join(unknown)}")
    missing = sorted(_REQUIRED_FIELDS - set(row))
    if missing:
        raise ValueError(f"row_{index}:missing_fields:{','.join(missing)}")

    pricing_event = row["pricing_event"]
    if not isinstance(pricing_event, bool):
        raise ValueError(f"row_{index}.pricing_event:must_be_boolean")

    actual_new = _finite_number(row["actual_new_money"], field=f"row_{index}.actual_new_money")
    predicted_new = _finite_number(
        row["predicted_new_money"], field=f"row_{index}.predicted_new_money"
    )
    actual_rollover = _finite_number(
        row["actual_rollover"], field=f"row_{index}.actual_rollover"
    )
    predicted_rollover = _finite_number(
        row["predicted_rollover"], field=f"row_{index}.predicted_rollover"
    )
    maturity = _finite_number(row["maturity_amount"], field=f"row_{index}.maturity_amount")

    amounts = {
        "actual_new_money": actual_new,
        "predicted_new_money": predicted_new,
        "actual_rollover": actual_rollover,
        "predicted_rollover": predicted_rollover,
        "maturity_amount": maturity,
    }
    for name, value in amounts.items():
        if value < 0:
            raise ValueError(f"row_{index}.{name}:must_be_non_negative")

    if actual_rollover > maturity + _AMOUNT_TOLERANCE:
        raise ValueError(f"row_{index}.actual_rollover:exceeds_maturity")
    if predicted_rollover > maturity + _AMOUNT_TOLERANCE:
        raise ValueError(f"row_{index}.predicted_rollover:exceeds_maturity")

    baseline_total: float | None = None
    if "baseline_total" in row and row["baseline_total"] is not None:
        baseline_total = _finite_number(row["baseline_total"], field=f"row_{index}.baseline_total")
        if baseline_total < 0:
            raise ValueError(f"row_{index}.baseline_total:must_be_non_negative")
    if pricing_event and baseline_total is None:
        raise ValueError(f"row_{index}.baseline_total:required_for_pricing_event")

    return {
        "actual_new_money": actual_new,
        "predicted_new_money": predicted_new,
        "actual_rollover": actual_rollover,
        "predicted_rollover": predicted_rollover,
        "maturity_amount": maturity,
        "pricing_event": pricing_event,
        "baseline_total": baseline_total,
    }


def score_backtest_records(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """OOS rows를 promotion protocol의 공통 metric으로 점수화한다.

    Metric 정의:
    - total_wape: 총수신 absolute error 합 / 실제 총수신 합
    - new_money_wape: 신규수신 absolute error 합 / 실제 신규수신 합
    - rollover_rate_mae_pp: 만기금액으로 가중한 재예치율 absolute error (%p)
    - bias_ratio: 총수신 signed error 합 / 실제 총수신 합
    - event_direction_accuracy: 금리변경 event에서 baseline 대비 실제/예측 증감 방향 일치율
    """
    if not rows:
        return {
            "version": EVALUATOR_VERSION,
            "status": "invalid",
            "errors": ["no_backtest_rows"],
            "metrics": None,
            "row_count": 0,
            "pricing_event_count": 0,
        }

    validated: list[dict[str, float | bool | None]] = []
    errors: list[str] = []
    for index, row in enumerate(rows):
        try:
            validated.append(validate_backtest_record(row, index=index))
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        return {
            "version": EVALUATOR_VERSION,
            "status": "invalid",
            "errors": errors,
            "metrics": None,
            "row_count": len(rows),
            "pricing_event_count": 0,
        }

    total_actual_sum = 0.0
    total_abs_error = 0.0
    total_signed_error = 0.0
    new_actual_sum = 0.0
    new_abs_error = 0.0
    maturity_sum = 0.0
    rollover_abs_error = 0.0
    event_count = 0
    event_direction_matches = 0

    for row in validated:
        actual_new = float(row["actual_new_money"])
        predicted_new = float(row["predicted_new_money"])
        actual_rollover = float(row["actual_rollover"])
        predicted_rollover = float(row["predicted_rollover"])
        maturity = float(row["maturity_amount"])

        actual_total = actual_new + actual_rollover
        predicted_total = predicted_new + predicted_rollover

        total_actual_sum += actual_total
        total_abs_error += abs(predicted_total - actual_total)
        total_signed_error += predicted_total - actual_total
        new_actual_sum += actual_new
        new_abs_error += abs(predicted_new - actual_new)
        maturity_sum += maturity
        rollover_abs_error += abs(predicted_rollover - actual_rollover)

        if bool(row["pricing_event"]):
            event_count += 1
            baseline = float(row["baseline_total"])
            if _direction(actual_total - baseline) == _direction(predicted_total - baseline):
                event_direction_matches += 1

    denominator_errors: list[str] = []
    if total_actual_sum <= _AMOUNT_TOLERANCE:
        denominator_errors.append("actual_total_sum_must_be_positive")
    if new_actual_sum <= _AMOUNT_TOLERANCE:
        denominator_errors.append("actual_new_money_sum_must_be_positive")
    if maturity_sum <= _AMOUNT_TOLERANCE:
        denominator_errors.append("maturity_sum_must_be_positive")
    if event_count == 0:
        denominator_errors.append("pricing_event_rows_required_for_direction_metric")

    if denominator_errors:
        return {
            "version": EVALUATOR_VERSION,
            "status": "invalid",
            "errors": denominator_errors,
            "metrics": None,
            "row_count": len(validated),
            "pricing_event_count": event_count,
        }

    metrics = {
        "total_wape": total_abs_error / total_actual_sum,
        "new_money_wape": new_abs_error / new_actual_sum,
        "rollover_rate_mae_pp": rollover_abs_error / maturity_sum * 100.0,
        "bias_ratio": total_signed_error / total_actual_sum,
        "event_direction_accuracy": event_direction_matches / event_count,
    }
    return {
        "version": EVALUATOR_VERSION,
        "status": "valid",
        "errors": [],
        "metrics": metrics,
        "row_count": len(validated),
        "pricing_event_count": event_count,
    }
