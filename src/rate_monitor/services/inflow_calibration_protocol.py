"""내부자료 수령 전 수신예측 calibration 연구·승격 프로토콜.

이 모듈은 실제 내부자료를 읽거나 모델을 학습하지 않는다. 공개 저장소에서 미리
고정할 수 있는 feature allowlist, 후보 모델군, 시간순 OOS split, champion/challenger
승격 Gate만 정의한다.

실제 내부자료와 추정계수, feature importance, training diagnostics는 별도 confidential
runtime에서만 다룬다. 이 프로토콜이 ``eligible_for_human_review``를 반환해도 자동으로
운영 모델을 교체하지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

PROTOCOL_VERSION = "inflow-calibration-protocol-v1"

MIN_RESEARCH_OBSERVATION_DATES = 24
MIN_PROMOTION_OBSERVATION_DATES = 36
MIN_TRAIN_OBSERVATION_DATES = 24
OOS_WINDOW_DATES = 3
MIN_PROMOTION_FOLDS = 4
MIN_PRICING_EVENT_OOS_COUNT = 6

MIN_PRIMARY_RELATIVE_IMPROVEMENT = 0.05
MIN_IMPROVED_FOLD_SHARE = 0.75
MAX_SINGLE_FOLD_RELATIVE_REGRESSION = 0.10
MAX_COMPONENT_RELATIVE_REGRESSION = 0.05
MAX_ABS_BIAS_RATIO = 0.05
MIN_EVENT_DIRECTION_ACCURACY = 0.55

PRIMARY_METRIC = "total_wape"


@dataclass(frozen=True)
class ModelCandidateSpec:
    """내부자료 수령 후 private runtime에서 검증할 후보 모델 계약."""

    key: str
    label: str
    family: str
    role: str
    minimum_observation_dates: int
    feature_groups: tuple[str, ...]
    target_components: tuple[str, ...]
    notes: str


FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "pricing": (
        "own_rate_pct",
        "rate_change_bp",
        "market_gap_bp",
        "market_rank_best",
        "market_rank_worst",
        "market_tie_count",
        "market_within_5bp_count",
    ),
    "product": (
        "product_key",
        "term_months",
        "channel_segment",
        "special_offer_flag",
    ),
    "flow_lags": (
        "lag_1_new_money_amount",
        "lag_3_new_money_mean",
        "lag_1_early_withdrawal_amount",
        "maturity_amount",
        "prior_rollover_rate_pct",
    ),
    "external_context": (
        "bok_base_rate_pct",
        "sector_deposit_rate_pct",
    ),
    "seasonality": (
        "month_sin",
        "month_cos",
    ),
}

APPROVED_FEATURES = frozenset(
    feature for features in FEATURE_GROUPS.values() for feature in features
)

FORBIDDEN_FEATURES = frozenset(
    {
        "new_money_amount",
        "new_account_count",
        "end_balance",
        "rollover_amount",
        "rollover_account_count",
        "early_withdrawal_amount",
        "early_withdrawal_account_count",
        "ftp_rate_pct",
        "customer_name",
        "account_number",
        "resident_registration_number",
        "rrn",
        "phone",
        "mobile_phone",
        "email",
        "home_address",
    }
)

_FORBIDDEN_PREFIXES = ("future_", "target_", "label_", "outcome_")

MODEL_CANDIDATES: tuple[ModelCandidateSpec, ...] = (
    ModelCandidateSpec(
        key="structural_v2_reference",
        label="Public Structural v2 reference",
        family="fixed_structural_reference",
        role="incumbent_reference",
        minimum_observation_dates=0,
        feature_groups=("pricing", "product", "flow_lags"),
        target_components=("new_money", "rollover", "total"),
        notes="현재 공개 구조 시나리오를 OOS 비교 기준선으로만 사용한다.",
    ),
    ModelCandidateSpec(
        key="regularized_elasticity_v1",
        label="Regularized elasticity challenger",
        family="interpretable_regularized_response",
        role="challenger",
        minimum_observation_dates=MIN_RESEARCH_OBSERVATION_DATES,
        feature_groups=("pricing", "product", "flow_lags", "external_context", "seasonality"),
        target_components=("new_money", "rollover", "total"),
        notes=(
            "첫 번째 필수 challenger. 금리·시장 gap·lag·만기·외부 context의 방향과 "
            "안정성을 설명 가능한 형태로 검증한다."
        ),
    ),
    ModelCandidateSpec(
        key="segment_interaction_v1",
        label="Segment interaction challenger",
        family="regularized_segment_interactions",
        role="challenger",
        minimum_observation_dates=MIN_PROMOTION_OBSERVATION_DATES,
        feature_groups=("pricing", "product", "flow_lags", "external_context", "seasonality"),
        target_components=("new_money", "rollover", "total"),
        notes="상품·기간·채널별 반응 차이는 표본수가 충분한 segment에서만 허용한다.",
    ),
    ModelCandidateSpec(
        key="nonlinear_residual_v1",
        label="Nonlinear residual challenger",
        family="nonlinear_residual_on_interpretable_baseline",
        role="challenger",
        minimum_observation_dates=60,
        feature_groups=("pricing", "product", "flow_lags", "external_context", "seasonality"),
        target_components=("new_money", "rollover", "total"),
        notes=(
            "비선형성은 충분한 history에서만 검토하고, 해석 가능한 challenger 대비 "
            "실질 OOS 개선이 있을 때만 승격 후보가 된다."
        ),
    ),
)

_REQUIRED_METRICS = frozenset(
    {
        "total_wape",
        "new_money_wape",
        "rollover_rate_mae_pp",
        "bias_ratio",
        "event_direction_accuracy",
    }
)


def protocol_summary() -> dict[str, Any]:
    """문서·테스트에서 사용할 공개 가능한 프로토콜 요약을 반환한다."""
    return {
        "version": PROTOCOL_VERSION,
        "primary_metric": PRIMARY_METRIC,
        "minimum_research_observation_dates": MIN_RESEARCH_OBSERVATION_DATES,
        "minimum_promotion_observation_dates": MIN_PROMOTION_OBSERVATION_DATES,
        "minimum_train_observation_dates": MIN_TRAIN_OBSERVATION_DATES,
        "oos_window_dates": OOS_WINDOW_DATES,
        "minimum_promotion_folds": MIN_PROMOTION_FOLDS,
        "minimum_pricing_event_oos_count": MIN_PRICING_EVENT_OOS_COUNT,
        "minimum_primary_relative_improvement": MIN_PRIMARY_RELATIVE_IMPROVEMENT,
        "minimum_improved_fold_share": MIN_IMPROVED_FOLD_SHARE,
        "maximum_single_fold_relative_regression": MAX_SINGLE_FOLD_RELATIVE_REGRESSION,
        "maximum_component_relative_regression": MAX_COMPONENT_RELATIVE_REGRESSION,
        "maximum_abs_bias_ratio": MAX_ABS_BIAS_RATIO,
        "minimum_event_direction_accuracy": MIN_EVENT_DIRECTION_ACCURACY,
        "feature_policy": "allowlist_fail_closed_as_of_only",
        "tuning_policy": "tune_within_train_window_only",
        "promotion_policy": "human_review_required_no_auto_promotion",
        "private_runtime_required": True,
        "model_coefficients_changed": False,
        "database_written": False,
    }


def model_candidate_registry() -> list[dict[str, Any]]:
    """후보 모델군을 deterministic한 순서로 반환한다."""
    return [asdict(candidate) for candidate in MODEL_CANDIDATES]


def _candidate(key: str) -> ModelCandidateSpec | None:
    return next((candidate for candidate in MODEL_CANDIDATES if candidate.key == key), None)


def validate_feature_columns(columns: list[str] | tuple[str, ...] | set[str]) -> dict[str, Any]:
    """Private feature table에서 모델 입력으로 사용할 열을 fail-closed 검증한다."""
    normalized = {str(column).strip() for column in columns if str(column).strip()}
    forbidden = sorted(
        column
        for column in normalized
        if column in FORBIDDEN_FEATURES or column.startswith(_FORBIDDEN_PREFIXES)
    )
    unknown = sorted(normalized - APPROVED_FEATURES - set(forbidden))
    missing_core = sorted({"own_rate_pct", "rate_change_bp", "term_months"} - normalized)

    errors: list[str] = []
    if forbidden:
        errors.append("forbidden_or_leaky_features:" + ",".join(forbidden))
    if unknown:
        errors.append("unknown_features:" + ",".join(unknown))
    if missing_core:
        errors.append("missing_core_features:" + ",".join(missing_core))

    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "approved_features": sorted(normalized & APPROVED_FEATURES),
        "forbidden_features": forbidden,
        "unknown_features": unknown,
        "as_of_policy": (
            "각 feature는 target 기간 시작 전에 확정된 값만 사용하며 contemporaneous/future "
            "outcome으로 재계산하지 않는다."
        ),
    }


def _parse_period(value: str) -> date:
    text = str(value).strip()
    for candidate in (text, f"{text}-01" if len(text) == 7 else text):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    raise ValueError(f"invalid_observation_date:{value}")


def build_expanding_window_splits(
    observation_dates: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    """월/일 관측일을 이용해 expanding-window OOS split을 만든다.

    최소 24개 관측일을 학습에 사용하고 이후 3개 관측일씩 OOS 평가한다. 마지막 fold는
    최종 holdout으로 표시한다. 동일 관측일 중복은 하나로 취급한다.
    """
    parsed = sorted({_parse_period(value) for value in observation_dates})
    folds: list[dict[str, Any]] = []
    train_end = MIN_TRAIN_OBSERVATION_DATES

    while train_end + OOS_WINDOW_DATES <= len(parsed):
        test_end = train_end + OOS_WINDOW_DATES
        train = parsed[:train_end]
        test = parsed[train_end:test_end]
        folds.append(
            {
                "fold": len(folds) + 1,
                "role": "development_oos",
                "train_start": train[0].isoformat(),
                "train_end": train[-1].isoformat(),
                "test_start": test[0].isoformat(),
                "test_end": test[-1].isoformat(),
                "train_observation_dates": len(train),
                "test_observation_dates": len(test),
            }
        )
        train_end = test_end

    if folds:
        folds[-1]["role"] = "final_holdout"
    return folds


def _finite_metric(metrics: dict[str, float], name: str) -> float | None:
    if name not in metrics or isinstance(metrics[name], bool):
        return None
    try:
        value = float(metrics[name])
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _validate_metric_bundle(metrics: dict[str, float], label: str) -> list[str]:
    errors: list[str] = []
    missing = sorted(_REQUIRED_METRICS - set(metrics))
    if missing:
        errors.append(f"{label}:missing_metrics:{','.join(missing)}")
        return errors

    for name in _REQUIRED_METRICS:
        value = _finite_metric(metrics, name)
        if value is None:
            errors.append(f"{label}:invalid_metric:{name}")
            continue
        if name in {"total_wape", "new_money_wape", "rollover_rate_mae_pp"} and value < 0:
            errors.append(f"{label}:negative_metric:{name}")
        if name == "event_direction_accuracy" and not 0 <= value <= 1:
            errors.append(f"{label}:event_direction_accuracy_out_of_range")
    return errors


def assess_challenger_promotion(
    *,
    candidate_key: str,
    observation_date_count: int,
    pricing_event_oos_count: int,
    feature_columns: list[str] | tuple[str, ...] | set[str],
    challenger_metrics: dict[str, float],
    incumbent_metrics: dict[str, float],
    fold_metrics: list[dict[str, float | str]],
) -> dict[str, Any]:
    """OOS 결과가 champion 교체 검토 대상으로 충분한지 보수적으로 판정한다.

    이 함수는 실제 모델 학습이나 승격을 수행하지 않는다. 통과 결과는
    ``eligible_for_human_review``일 뿐이며 운영 champion 교체에는 별도 검토가 필요하다.
    """
    reasons: list[str] = []
    candidate = _candidate(candidate_key)
    if candidate is None or candidate.role != "challenger":
        reasons.append("unknown_or_non_challenger_candidate")

    feature_report = validate_feature_columns(feature_columns)
    if feature_report["status"] != "valid":
        reasons.extend(feature_report["errors"])

    minimum_candidate_dates = (
        candidate.minimum_observation_dates
        if candidate is not None
        else MIN_PROMOTION_OBSERVATION_DATES
    )
    required_dates = max(MIN_PROMOTION_OBSERVATION_DATES, minimum_candidate_dates)
    if observation_date_count < required_dates:
        reasons.append(f"insufficient_observation_dates:{observation_date_count}<{required_dates}")
    if pricing_event_oos_count < MIN_PRICING_EVENT_OOS_COUNT:
        reasons.append(
            f"insufficient_pricing_event_oos_count:{pricing_event_oos_count}"
            f"<{MIN_PRICING_EVENT_OOS_COUNT}"
        )
    if len(fold_metrics) < MIN_PROMOTION_FOLDS:
        reasons.append(f"insufficient_oos_folds:{len(fold_metrics)}<{MIN_PROMOTION_FOLDS}")

    reasons.extend(_validate_metric_bundle(challenger_metrics, "challenger"))
    reasons.extend(_validate_metric_bundle(incumbent_metrics, "incumbent"))

    primary_improvement: float | None = None
    improved_fold_share: float | None = None
    if not any("metric" in reason for reason in reasons):
        challenger_total = float(challenger_metrics[PRIMARY_METRIC])
        incumbent_total = float(incumbent_metrics[PRIMARY_METRIC])
        if incumbent_total <= 0:
            reasons.append("incumbent_primary_metric_must_be_positive")
        else:
            primary_improvement = (incumbent_total - challenger_total) / incumbent_total
            if primary_improvement < MIN_PRIMARY_RELATIVE_IMPROVEMENT:
                reasons.append(
                    "primary_improvement_below_gate:"
                    f"{primary_improvement:.6f}<{MIN_PRIMARY_RELATIVE_IMPROVEMENT:.6f}"
                )

        for component in ("new_money_wape", "rollover_rate_mae_pp"):
            challenger_component = float(challenger_metrics[component])
            incumbent_component = float(incumbent_metrics[component])
            if incumbent_component <= 0:
                reasons.append(f"incumbent_component_metric_must_be_positive:{component}")
            elif challenger_component > incumbent_component * (
                1 + MAX_COMPONENT_RELATIVE_REGRESSION
            ):
                reasons.append(f"component_regression:{component}")

        if abs(float(challenger_metrics["bias_ratio"])) > MAX_ABS_BIAS_RATIO:
            reasons.append("absolute_bias_above_gate")
        if (
            float(challenger_metrics["event_direction_accuracy"])
            < MIN_EVENT_DIRECTION_ACCURACY
        ):
            reasons.append("event_direction_accuracy_below_gate")

    valid_fold_count = 0
    improved_folds = 0
    final_holdouts = 0
    for index, row in enumerate(fold_metrics):
        challenger_fold = _finite_metric(row, "challenger_total_wape")  # type: ignore[arg-type]
        incumbent_fold = _finite_metric(row, "incumbent_total_wape")  # type: ignore[arg-type]
        role = row.get("role")
        if challenger_fold is None or incumbent_fold is None or incumbent_fold <= 0:
            reasons.append(f"fold_{index + 1}:invalid_primary_metric")
            continue
        valid_fold_count += 1
        if challenger_fold < incumbent_fold:
            improved_folds += 1
        relative_regression = (challenger_fold - incumbent_fold) / incumbent_fold
        if relative_regression > MAX_SINGLE_FOLD_RELATIVE_REGRESSION:
            reasons.append(f"fold_{index + 1}:catastrophic_regression")
        if role == "final_holdout":
            final_holdouts += 1
            if challenger_fold >= incumbent_fold:
                reasons.append("final_holdout_not_better_than_incumbent")

    if fold_metrics and final_holdouts != 1:
        reasons.append(f"final_holdout_count_must_equal_one:{final_holdouts}")
    if valid_fold_count:
        improved_fold_share = improved_folds / valid_fold_count
        if improved_fold_share < MIN_IMPROVED_FOLD_SHARE:
            reasons.append(
                "improved_fold_share_below_gate:"
                f"{improved_fold_share:.6f}<{MIN_IMPROVED_FOLD_SHARE:.6f}"
            )

    status = "eligible_for_human_review" if not reasons else "blocked"
    return {
        "version": PROTOCOL_VERSION,
        "status": status,
        "candidate_key": candidate_key,
        "primary_metric": PRIMARY_METRIC,
        "primary_relative_improvement": primary_improvement,
        "improved_fold_share": improved_fold_share,
        "reasons": reasons,
        "feature_report": feature_report,
        "auto_promote": False,
        "human_review_required": True,
        "private_runtime_required": True,
        "model_coefficients_changed": False,
        "database_written": False,
    }
