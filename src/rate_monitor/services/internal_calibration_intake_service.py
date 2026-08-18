"""Stage E0 내부 수신실적 calibration intake 품질 Gate.

이 모듈은 은행 내부 원본 Excel/CSV 형식을 강제하지 않는다. 실제 자료를 받으면
별도 adapter에서 원본 열을 아래 canonical dataset으로 매핑한 뒤 이 Gate를
통과시킨다. 여기서는 DB write나 예측계수 calibration을 수행하지 않는다.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

MIN_HISTORY_DAYS = 365 * 2
RECOMMENDED_HISTORY_DAYS = 365 * 3
MIN_PRICING_OBSERVATION_DATES = 24
RECOMMENDED_PRICING_OBSERVATION_DATES = 36

REQUIRED_DATASETS = (
    "pricing_flow",
    "maturity_rollover",
    "early_withdrawal",
    "pricing_events",
    "ftp",
)

OPTIONAL_DATASETS = (
    "channel_segments",
    "preference_performance",
)

CONTRACTS: dict[str, dict[str, tuple[str, ...] | str]] = {
    "pricing_flow": {
        "required": (
            "date",
            "product_key",
            "term_months",
            "applied_rate_pct",
            "new_money_amount",
            "new_account_count",
            "end_balance",
        ),
        "date_field": "date",
    },
    "maturity_rollover": {
        "required": (
            "date",
            "product_key",
            "term_months",
            "maturity_amount",
            "maturity_account_count",
            "rollover_amount",
            "rollover_account_count",
        ),
        "date_field": "date",
    },
    "early_withdrawal": {
        "required": (
            "date",
            "product_key",
            "term_months",
            "early_withdrawal_amount",
            "early_withdrawal_account_count",
        ),
        "date_field": "date",
    },
    "pricing_events": {
        "required": (
            "start_date",
            "product_key",
            "term_months",
            "rate_before_pct",
            "rate_after_pct",
            "special_offer_flag",
        ),
        "date_field": "start_date",
    },
    "ftp": {
        "required": ("date", "term_months", "ftp_rate_pct"),
        "date_field": "date",
    },
    "channel_segments": {
        "required": ("date", "product_key", "term_months", "segment", "amount"),
        "date_field": "date",
    },
    "preference_performance": {
        "required": (
            "date",
            "product_key",
            "term_months",
            "preference_code",
            "eligible_count",
            "achieved_count",
            "achieved_amount",
            "preference_rate_bp",
        ),
        "date_field": "date",
    },
}

_PII_KEYS = {
    "customer_name",
    "account_number",
    "resident_registration_number",
    "rrn",
    "phone",
    "mobile_phone",
    "email",
    "home_address",
}

_RATE_FIELDS = {
    "applied_rate_pct",
    "rate_before_pct",
    "rate_after_pct",
    "ftp_rate_pct",
}
_COUNT_SUFFIXES = ("_count",)
_AMOUNT_TOKENS = ("amount", "balance")


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y%m%d", "%Y%m"):
            try:
                parsed = datetime.strptime(text, fmt)
            except ValueError:
                continue
            return parsed.date()
    return None


def _finite_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _dataset_report(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    contract = CONTRACTS[name]
    required = tuple(contract["required"])
    date_field = str(contract["date_field"])
    errors: list[str] = []
    warnings: list[str] = []
    observed_dates: list[date] = []

    if not rows:
        return {
            "dataset": name,
            "status": "no_data",
            "row_count": 0,
            "errors": ["dataset_has_no_rows"],
            "warnings": [],
            "min_date": None,
            "max_date": None,
            "unique_date_count": 0,
        }

    seen_pii: set[str] = set()
    for row_index, row in enumerate(rows):
        keys = set(row)
        seen_pii.update(keys & _PII_KEYS)
        missing = [field for field in required if row.get(field) in (None, "")]
        if missing:
            errors.append(f"row_{row_index}:missing_required:{','.join(sorted(missing))}")
            continue

        parsed_date = _as_date(row.get(date_field))
        if parsed_date is None:
            errors.append(f"row_{row_index}:invalid_date:{date_field}")
        else:
            observed_dates.append(parsed_date)

        term = _finite_number(row.get("term_months"))
        if term is not None and (term <= 0 or not float(term).is_integer()):
            errors.append(f"row_{row_index}:invalid_term_months")

        for field in required:
            if field in {
                date_field,
                "product_key",
                "special_offer_flag",
                "segment",
                "preference_code",
            }:
                continue
            value = _finite_number(row.get(field))
            if value is None:
                errors.append(f"row_{row_index}:invalid_number:{field}")
                continue
            if field in _RATE_FIELDS and not 0 <= value <= 100:
                errors.append(f"row_{row_index}:rate_out_of_range:{field}")
            if field.endswith(_COUNT_SUFFIXES) and value < 0:
                errors.append(f"row_{row_index}:negative_count:{field}")
            if any(token in field for token in _AMOUNT_TOKENS) and value < 0:
                errors.append(f"row_{row_index}:negative_amount:{field}")

    if seen_pii:
        errors.append("pii_fields_not_allowed:" + ",".join(sorted(seen_pii)))

    unique_errors = sorted(set(errors))
    unique_dates = set(observed_dates)
    if len(observed_dates) != len(unique_dates):
        warnings.append("duplicate_dates_present")

    return {
        "dataset": name,
        "status": "valid" if not unique_errors else "invalid",
        "row_count": len(rows),
        "errors": unique_errors,
        "warnings": warnings,
        "min_date": min(observed_dates).isoformat() if observed_dates else None,
        "max_date": max(observed_dates).isoformat() if observed_dates else None,
        "unique_date_count": len(unique_dates),
    }


def assess_internal_calibration_bundle(
    bundle: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Canonical 내부자료 bundle의 calibration 준비상태를 평가한다.

    원본 파일의 열 이름/시트 구조는 이 함수의 계약이 아니다. 자료 수령 후 adapter가
    canonical dataset으로 변환한 결과만 검사한다.
    """
    missing_datasets = [name for name in REQUIRED_DATASETS if not bundle.get(name)]
    reports = [
        _dataset_report(name, bundle.get(name, []))
        for name in (*REQUIRED_DATASETS, *OPTIONAL_DATASETS)
        if name in bundle or name in REQUIRED_DATASETS
    ]

    pricing_report = next(report for report in reports if report["dataset"] == "pricing_flow")
    history_days: int | None = None
    if pricing_report["min_date"] and pricing_report["max_date"]:
        history_days = (
            date.fromisoformat(pricing_report["max_date"])
            - date.fromisoformat(pricing_report["min_date"])
        ).days
    observation_dates = int(pricing_report["unique_date_count"])

    dataset_errors = [
        report["dataset"] for report in reports if report["status"] != "valid"
    ]
    if missing_datasets:
        status = "missing_required_data"
    elif dataset_errors:
        status = "data_quality_failed"
    elif (
        history_days is None
        or history_days < MIN_HISTORY_DAYS
        or observation_dates < MIN_PRICING_OBSERVATION_DATES
    ):
        status = "insufficient_history"
    else:
        status = "ready_for_calibration"

    history_grade = "insufficient"
    if (
        history_days is not None
        and history_days >= RECOMMENDED_HISTORY_DAYS
        and observation_dates >= RECOMMENDED_PRICING_OBSERVATION_DATES
    ):
        history_grade = "recommended_36m_plus"
    elif (
        history_days is not None
        and history_days >= MIN_HISTORY_DAYS
        and observation_dates >= MIN_PRICING_OBSERVATION_DATES
    ):
        history_grade = "minimum_24m_plus"

    return {
        "version": "internal-calibration-intake-v1",
        "status": status,
        "source_format_contract": "not_fixed_map_source_columns_before_validation",
        "pii_policy": "direct_identifiers_not_allowed",
        "required_datasets": list(REQUIRED_DATASETS),
        "optional_datasets": list(OPTIONAL_DATASETS),
        "missing_required_datasets": missing_datasets,
        "history_days": history_days,
        "pricing_observation_dates": observation_dates,
        "history_grade": history_grade,
        "minimum_history_days": MIN_HISTORY_DAYS,
        "recommended_history_days": RECOMMENDED_HISTORY_DAYS,
        "minimum_pricing_observation_dates": MIN_PRICING_OBSERVATION_DATES,
        "recommended_pricing_observation_dates": RECOMMENDED_PRICING_OBSERVATION_DATES,
        "datasets": reports,
        "calibration_allowed": status == "ready_for_calibration",
        "model_coefficients_changed": False,
        "database_written": False,
    }
