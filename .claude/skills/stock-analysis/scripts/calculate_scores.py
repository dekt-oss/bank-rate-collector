#!/usr/bin/env python3
"""Calculate stock-analysis scores deterministically.

Input JSON example:
{
  "fundamental": {
    "valuation": 7.5,
    "earnings_outlook": 8.0,
    "business_quality": 7.0,
    "catalysts": 7.5,
    "downside_resilience": 6.5,
    "capital_allocation": null
  },
  "timing": {
    "technical": 6.0,
    "flows_positioning": 7.0,
    "event_setup": 6.5,
    "sentiment": 5.5
  },
  "confidence": {
    "source_quality": 8.5,
    "freshness": 8.0,
    "consistency": 7.5
  }
}

Any component may be null (N/A). Available weights are renormalized for the
partial dimension score. If a component in CRITICAL_FOR_OVERALL is missing,
the overall purchase-attractiveness score is NOT produced; the partial
fundamental score is still reported with analysis_status
"insufficient_evidence". Missing evidence lowers coverage/confidence and is
never converted into a fabricated score.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

FUNDAMENTAL_WEIGHTS = {
    "valuation": 0.25,
    "earnings_outlook": 0.20,
    "business_quality": 0.20,
    "catalysts": 0.15,
    "downside_resilience": 0.15,
    "capital_allocation": 0.05,
}

TIMING_WEIGHTS = {
    "technical": 0.40,
    "flows_positioning": 0.30,
    "event_setup": 0.20,
    "sentiment": 0.10,
}

CONFIDENCE_WEIGHTS = {
    "source_quality": 0.35,
    "coverage": 0.30,
    "freshness": 0.20,
    "consistency": 0.15,
}

# Components whose absence makes an overall purchase-attractiveness score
# meaningless. They MAY be null (never fabricate a score without evidence);
# the consequence is that overall is not produced.
MIN_TIMING_COVERAGE_FOR_OVERALL = 0.50
MIN_TIMING_COVERAGE_FOR_COMPLETE = 0.70

CRITICAL_FOR_OVERALL = {
    "valuation",
    "earnings_outlook",
    "business_quality",
    "downside_resilience",
}


def require_object(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def validate_score(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number from 0 to 10 or null")
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 10:
        raise ValueError(f"{label} must be between 0 and 10")
    return value


def weighted_dimension(values: dict[str, Any], weights: dict[str, float], label: str) -> dict[str, Any]:
    unknown = sorted(set(values) - set(weights))
    if unknown:
        raise ValueError(f"Unknown {label} component(s): {', '.join(unknown)}")

    numerator = 0.0
    available_weight = 0.0
    missing: list[str] = []
    normalized: dict[str, float | None] = {}

    for key, weight in weights.items():
        value = validate_score(values.get(key), f"{label}.{key}")
        normalized[key] = value
        if value is None:
            missing.append(key)
        else:
            numerator += value * weight
            available_weight += weight

    if available_weight == 0:
        return {
            "score": None,
            "coverage": 0.0,
            "missing": missing,
            "components": normalized,
        }

    return {
        "score": round(numerator / available_weight, 1),
        "coverage": round(available_weight, 4),
        "missing": missing,
        "components": normalized,
    }


def attractiveness_label(score: float | None) -> str:
    if score is None:
        return "not scorable"
    if score >= 8.5:
        return "very high attractiveness"
    if score >= 7.0:
        return "positive / staged entry"
    if score >= 5.5:
        return "neutral"
    if score >= 4.0:
        return "low attractiveness"
    return "very low attractiveness"


def confidence_grade(score: float) -> str:
    if score >= 8.5:
        return "A"
    if score >= 7.0:
        return "B"
    if score >= 5.5:
        return "C"
    return "D"


def apply_confidence_cap(grade: str, cap: str) -> str:
    order = ["A", "B", "C", "D"]
    return order[max(order.index(grade), order.index(cap))]


def calculate(payload: dict[str, Any]) -> dict[str, Any]:
    fundamental_input = require_object(payload.get("fundamental"), "fundamental")
    timing_input = require_object(payload.get("timing"), "timing")

    fundamental = weighted_dimension(fundamental_input, FUNDAMENTAL_WEIGHTS, "fundamental")
    timing = weighted_dimension(timing_input, TIMING_WEIGHTS, "timing")

    price_verified = payload.get("price_verified", True)
    if not isinstance(price_verified, bool):
        raise ValueError("price_verified must be true or false")

    critical_missing = sorted(CRITICAL_FOR_OVERALL & set(fundamental["missing"]))

    if not price_verified:
        overall = None
        overall_basis = "price_unverified"
    elif critical_missing or fundamental["score"] is None:
        overall = None
        overall_basis = "insufficient_critical_evidence"
    elif timing["score"] is None or timing["coverage"] < MIN_TIMING_COVERAGE_FOR_OVERALL:
        overall = None
        overall_basis = "fundamental_only"
    else:
        overall = round(fundamental["score"] * 0.70 + timing["score"] * 0.30, 1)
        overall_basis = "fundamental_and_timing"

    weighted_coverage = 0.70 * fundamental["coverage"] + 0.30 * timing["coverage"]
    coverage_score = weighted_coverage * 10

    confidence_input = require_object(payload.get("confidence"), "confidence")
    confidence_values = {
        "source_quality": validate_score(confidence_input.get("source_quality"), "confidence.source_quality"),
        "coverage": coverage_score,
        "freshness": validate_score(confidence_input.get("freshness"), "confidence.freshness"),
        "consistency": validate_score(confidence_input.get("consistency"), "confidence.consistency"),
    }

    if any(value is None for value in confidence_values.values()):
        missing = [key for key, value in confidence_values.items() if value is None]
        raise ValueError(f"Missing confidence input(s): {', '.join(missing)}")

    raw_confidence_score = sum(
        confidence_values[key] * weight for key, weight in CONFIDENCE_WEIGHTS.items()
    )
    grade = confidence_grade(raw_confidence_score)
    confidence_score = round(raw_confidence_score, 1)

    key_missing = set(fundamental["missing"])
    caps: list[str] = []
    if weighted_coverage < 0.50:
        caps.append("D")
    elif weighted_coverage < 0.70:
        caps.append("C")
    elif weighted_coverage < 0.85:
        caps.append("B")
    if {"valuation", "earnings_outlook"}.issubset(key_missing):
        caps.append("D")
    elif key_missing.intersection({"valuation", "earnings_outlook"}):
        caps.append("C")

    explicit_cap = confidence_input.get("grade_cap")
    if explicit_cap is not None:
        if explicit_cap not in {"A", "B", "C", "D"}:
            raise ValueError("confidence.grade_cap must be A, B, C, D, or omitted")
        caps.append(explicit_cap)

    for cap in caps:
        grade = apply_confidence_cap(grade, cap)

    provisional = (
        overall is None
        or bool(critical_missing)
        or weighted_coverage < 0.85
        or timing["coverage"] < MIN_TIMING_COVERAGE_FOR_COMPLETE
        or grade in {"C", "D"}
    )

    if not price_verified:
        analysis_status = "restricted"
    elif critical_missing or fundamental["score"] is None:
        analysis_status = "insufficient_evidence"
    elif overall_basis == "fundamental_only":
        analysis_status = "partial"
    elif grade == "D":
        analysis_status = "restricted"
    elif provisional:
        analysis_status = "provisional"
    else:
        analysis_status = "complete"

    label = attractiveness_label(overall)
    if provisional and label == "very high attractiveness":
        label = "positive / staged entry (capped: provisional evidence)"

    return {
        "fundamental": fundamental,
        "timing": timing,
        "overall": overall,
        "overall_basis": overall_basis,
        "label": label,
        "critical_missing": critical_missing,
        "weighted_coverage": round(weighted_coverage, 4),
        "confidence": {
            "score": confidence_score,
            "grade": grade,
            "inputs": {key: round(value, 1) for key, value in confidence_values.items()},
            "caps_applied": caps,
        },
        "provisional": provisional,
        "analysis_status": analysis_status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate stock-analysis scores from JSON input")
    parser.add_argument("input", type=Path, help="Path to input JSON")
    parser.add_argument("--output", type=Path, help="Optional output JSON path")
    args = parser.parse_args()

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Input JSON must be an object")
        result = calculate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
