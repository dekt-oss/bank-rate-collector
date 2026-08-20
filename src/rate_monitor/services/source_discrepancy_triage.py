"""저축은행 원천 불일치의 조사 우선순위를 read-only로 계산한다.

이 모듈은 mismatch report를 정렬·분류할 뿐 canonical observation, source precedence,
product identity를 수정하지 않는다. 점수는 데이터품질 조사 순서를 위한 deterministic
heuristic이며 금리의 정답을 자동 판정하는 authority score가 아니다.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from rate_monitor.domain.normalization import normalize_product_name
from rate_monitor.services.institution_matching import normalize_institution

TRIAGE_POLICY_VERSION = "2026-08-20-v1"
MISMATCH_STATUSES = {
    "rate_mismatch",
    "rate_mismatch_date_diff",
    "rate_mismatch_date_unknown",
    "incomplete_rate",
}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _decimal(value: object) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _date(value: object) -> date | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _key(
    institution: object,
    product: object,
    product_type: object,
    term_months: object,
) -> tuple[str, str, str, int | None]:
    term = None if term_months in {None, ""} else int(term_months)
    return (
        normalize_institution(institution),
        normalize_product_name(str(product or "")),
        str(product_type or ""),
        term,
    )


def _official_groups_by_key(
    report: dict[str, Any],
) -> dict[tuple[str, str, str, int | None], dict[str, Any]]:
    groups: dict[tuple[str, str, str, int | None], dict[str, Any]] = {}
    for group in report.get("official_evidence_groups", []):
        if not isinstance(group, dict):
            continue
        comparison_product = group.get("comparison_product") or group.get("official_product")
        key = _key(
            group.get("institution"),
            comparison_product,
            group.get("product_type"),
            group.get("term_months"),
        )
        groups[key] = group
    return groups


def _add_component(
    components: list[dict[str, int | str]],
    *,
    code: str,
    points: int,
) -> None:
    if points:
        components.append({"code": code, "points": points})


def _delta_points(delta_abs: Decimal | None) -> tuple[int, str | None]:
    if delta_abs is None:
        return 0, None
    if delta_abs >= Decimal("1.0"):
        return 30, "max_rate_gap_ge_1_00pp"
    if delta_abs >= Decimal("0.5"):
        return 24, "max_rate_gap_ge_0_50pp"
    if delta_abs >= Decimal("0.2"):
        return 16, "max_rate_gap_ge_0_20pp"
    if delta_abs >= Decimal("0.1"):
        return 10, "max_rate_gap_ge_0_10pp"
    if delta_abs > 0:
        return 5, "max_rate_gap_lt_0_10pp"
    return 0, None


def _gap_points(days: int | None) -> tuple[int, str | None]:
    if days is None:
        return 0, None
    if days >= 365:
        return 18, "effective_date_gap_ge_365d"
    if days >= 90:
        return 12, "effective_date_gap_ge_90d"
    if days >= 30:
        return 8, "effective_date_gap_ge_30d"
    if days >= 7:
        return 4, "effective_date_gap_ge_7d"
    return 0, None


def _age_points(days: int | None) -> tuple[int, str | None]:
    if days is None:
        return 0, None
    if days >= 365:
        return 20, "source_effective_age_ge_365d"
    if days >= 90:
        return 12, "source_effective_age_ge_90d"
    if days >= 30:
        return 6, "source_effective_age_ge_30d"
    return 0, None


def _official_points(signal: str | None) -> tuple[int, str | None]:
    mapping = {
        "official_conflict": (50, "official_evidence_conflict"),
        "neither_supported": (45, "official_supports_neither_source"),
        "primary_supported": (40, "official_supports_primary_only"),
        "secondary_supported": (40, "official_supports_secondary_only"),
        "both_supported": (35, "official_supports_both_despite_mismatch"),
        "mixed_support": (30, "official_evidence_mixed_support"),
    }
    return mapping.get(signal or "", (0, None))


def _classification(
    *,
    official_signal: str | None,
    status: str,
    max_source_age_days: int | None,
    delta_abs: Decimal | None,
) -> str:
    if official_signal == "official_conflict":
        return "official_conflict"
    if official_signal in {
        "neither_supported",
        "primary_supported",
        "secondary_supported",
        "both_supported",
        "mixed_support",
    }:
        return "official_evidence_discrepancy"
    if status == "rate_mismatch":
        return "same_effective_date_conflict"
    if max_source_age_days is not None and max_source_age_days >= 90:
        return "stale_source"
    if delta_abs is not None and delta_abs >= Decimal("0.2"):
        return "material_rate_gap"
    if status == "rate_mismatch_date_diff":
        return "freshness_gap"
    if status == "rate_mismatch_date_unknown":
        return "unknown_effective_date"
    return "incomplete_or_minor_drift"


def _priority(score: int, official_signal: str | None) -> str:
    if official_signal in {
        "official_conflict",
        "neither_supported",
        "primary_supported",
        "secondary_supported",
    }:
        return "P0"
    if score >= 80:
        return "P0"
    if score >= 55:
        return "P1"
    if score >= 35:
        return "P2"
    return "P3"


def _suggested_action(
    *,
    official_signal: str | None,
    status: str,
    max_source_age_days: int | None,
    delta_abs: Decimal | None,
) -> str:
    if official_signal == "official_conflict":
        return "공식 상품공시와 시행 공지의 최신성·적용범위를 먼저 확인한다."
    if official_signal == "neither_supported":
        return "공식 공시 기준으로 FSB와 FINLIFE 양쪽 raw payload와 수집 locator를 재검증한다."
    if official_signal == "primary_supported":
        return "공식 공시와 불일치하는 FINLIFE 값·기준일·수집시각을 재검증한다."
    if official_signal == "secondary_supported":
        return "공식 공시와 불일치하는 FSB 값·기준일·raw artifact를 재검증한다."
    if status == "rate_mismatch":
        return "동일 기준일인데 값이 다르므로 양 source raw payload를 직접 대조한다."
    if max_source_age_days is not None and max_source_age_days >= 90:
        return "오래된 source_effective_at이 남은 원천의 갱신 누락·stale carry-forward를 확인한다."
    if delta_abs is not None and delta_abs >= Decimal("0.2"):
        return "금리차가 커서 개별 저축은행 공식 공시 evidence를 우선 확보한다."
    if status == "rate_mismatch_date_diff":
        return "기준일 차이에 따른 정상 publication lag인지 최신 공식 공시로 확인한다."
    if status == "rate_mismatch_date_unknown":
        return "누락된 source_effective_at을 먼저 보강한 뒤 금리차를 재판정한다."
    return "공식 evidence를 확보하고 두 source의 현재값을 재확인한다."


def annotate_discrepancy_triage(report: dict[str, Any]) -> dict[str, Any]:
    """Mismatch 행에 deterministic 조사 우선순위를 부여한다."""
    official_by_key = _official_groups_by_key(report)
    generated_date = _date(report.get("generated_at"))
    queue: list[dict[str, Any]] = []

    status_points = {
        "rate_mismatch": 45,
        "rate_mismatch_date_unknown": 35,
        "incomplete_rate": 35,
        "rate_mismatch_date_diff": 20,
    }

    for match in report.get("matches", []):
        if not isinstance(match, dict):
            continue
        status = str(match.get("status") or "")
        if status not in MISMATCH_STATUSES:
            continue

        primary = match.get("primary") if isinstance(match.get("primary"), dict) else {}
        secondary = match.get("secondary") if isinstance(match.get("secondary"), dict) else {}
        key = _key(
            primary.get("institution") or secondary.get("institution"),
            primary.get("product") or secondary.get("product"),
            primary.get("product_type") or secondary.get("product_type"),
            (
                primary.get("term_months")
                if primary.get("term_months") is not None
                else secondary.get("term_months")
            ),
        )
        official = official_by_key.get(key)
        official_signal = (
            str(official.get("reconciliation_signal") or "")
            if isinstance(official, dict)
            else None
        ) or None

        max_cmp = match.get("max_rate_comparison")
        if not isinstance(max_cmp, dict):
            max_cmp = {}
        delta = _decimal(max_cmp.get("delta_primary_minus_secondary"))
        delta_abs = abs(delta) if delta is not None else None

        primary_date = _date(primary.get("source_effective_at"))
        secondary_date = _date(secondary.get("source_effective_at"))
        date_gap_days = (
            abs((primary_date - secondary_date).days)
            if primary_date is not None and secondary_date is not None
            else None
        )
        source_ages = [
            max((generated_date - candidate).days, 0)
            for candidate in (primary_date, secondary_date)
            if generated_date is not None and candidate is not None
        ]
        max_source_age_days = max(source_ages) if source_ages else None

        components: list[dict[str, int | str]] = []
        _add_component(
            components,
            code=f"status:{status}",
            points=status_points[status],
        )

        points, code = _official_points(official_signal)
        if code:
            _add_component(components, code=code, points=points)

        points, code = _delta_points(delta_abs)
        if code:
            _add_component(components, code=code, points=points)

        points, code = _gap_points(date_gap_days)
        if code and status != "rate_mismatch":
            _add_component(components, code=code, points=points)

        points, code = _age_points(max_source_age_days)
        if code:
            _add_component(components, code=code, points=points)

        score = min(sum(int(item["points"]) for item in components), 100)
        classification = _classification(
            official_signal=official_signal,
            status=status,
            max_source_age_days=max_source_age_days,
            delta_abs=delta_abs,
        )
        priority = _priority(score, official_signal)

        queue.append(
            {
                "rank": None,
                "priority": priority,
                "score": score,
                "classification": classification,
                "institution": primary.get("institution") or secondary.get("institution"),
                "product": primary.get("product") or secondary.get("product"),
                "product_type": primary.get("product_type") or secondary.get("product_type"),
                "term_months": (
                    primary.get("term_months")
                    if primary.get("term_months") is not None
                    else secondary.get("term_months")
                ),
                "status": status,
                "max_rate": {
                    "primary": max_cmp.get("primary"),
                    "secondary": max_cmp.get("secondary"),
                    "delta_primary_minus_secondary": max_cmp.get(
                        "delta_primary_minus_secondary"
                    ),
                    "absolute_delta": (
                        format(delta_abs, "f") if delta_abs is not None else None
                    ),
                },
                "effective_date": {
                    "primary": primary.get("source_effective_at"),
                    "secondary": secondary.get("source_effective_at"),
                    "gap_days": date_gap_days,
                    "max_source_age_days": max_source_age_days,
                },
                "official_evidence": (
                    {
                        "evidence_group": official.get("evidence_group"),
                        "status": official.get("status"),
                        "reconciliation_signal": official_signal,
                        "official_max_rates": official.get("official_max_rates"),
                        "source_support": official.get("source_support"),
                    }
                    if isinstance(official, dict)
                    else None
                ),
                "score_components": components,
                "suggested_action": _suggested_action(
                    official_signal=official_signal,
                    status=status,
                    max_source_age_days=max_source_age_days,
                    delta_abs=delta_abs,
                ),
                "provenance": {
                    "primary_source_id": primary.get("source_id"),
                    "secondary_source_id": secondary.get("source_id"),
                    "primary_raw_artifact_path": primary.get("raw_artifact_path"),
                    "secondary_raw_artifact_path": secondary.get("raw_artifact_path"),
                    "primary_source_locator": primary.get("base_source_locator"),
                    "secondary_source_locator": secondary.get("base_source_locator"),
                },
            }
        )

    queue.sort(
        key=lambda item: (
            PRIORITY_ORDER[str(item["priority"])],
            -int(item["score"]),
            -(_decimal(item["max_rate"]["absolute_delta"]) or Decimal("0")),
            str(item["institution"] or ""),
            str(item["product"] or ""),
            int(item["term_months"] or 0),
        )
    )

    institution_counts = Counter(str(item["institution"] or "") for item in queue)
    for rank, item in enumerate(queue, start=1):
        item["rank"] = rank
        item["institution_mismatch_count"] = institution_counts[
            str(item["institution"] or "")
        ]

    priority_counts = Counter(str(item["priority"]) for item in queue)
    classification_counts = Counter(str(item["classification"]) for item in queue)
    report["triage"] = {
        "policy_version": TRIAGE_POLICY_VERSION,
        "scope": "max_rate_mismatch_rows_only",
        "authority_semantics": (
            "investigation_priority_only; does_not_select_canonical_source"
        ),
        "thresholds": {
            "P0": ">=80 or direct official evidence gate",
            "P1": "55-79",
            "P2": "35-54",
            "P3": "<35",
        },
        "summary": {
            "queue_size": len(queue),
            "P0": priority_counts["P0"],
            "P1": priority_counts["P1"],
            "P2": priority_counts["P2"],
            "P3": priority_counts["P3"],
            "classifications": dict(sorted(classification_counts.items())),
            "institutions": len(institution_counts),
        },
        "queue": queue,
    }
    report.setdefault("summary", {})["triage_queue_size"] = len(queue)
    report["scope"]["triage_mutates_canonical"] = False
    report["scope"]["triage_selects_authority"] = False
    return report
