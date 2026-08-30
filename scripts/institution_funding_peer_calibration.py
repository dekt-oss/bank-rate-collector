"""Measure Direct Peer sample behavior on an actual canonical funding DB."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from rate_monitor.services.institution_funding_peer_db import load_funding_peer_points
from rate_monitor.services.institution_funding_peer_service import (
    select_direct_funding_peers,
)
from rate_monitor.services.institution_funding_position_service import (
    build_institution_funding_positions,
)


def _summary(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "median": None, "max": None}
    return {
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def calibrate(
    db_path: Path,
    *,
    sector: str,
    peer_counts: tuple[int, ...] = (12, 16, 20),
    minimum_peer_count: int = 8,
) -> dict[str, Any]:
    positions = build_institution_funding_positions(db_path)
    sector_payload = positions.get("sectors", {}).get(sector)
    if not sector_payload:
        raise RuntimeError(f"production funding position unavailable for sector={sector}")
    analysis_month = str(sector_payload["analysis_month"])
    points = load_funding_peer_points(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
    )
    by_id = {point.institution_id: point for point in points}
    if len(by_id) != len(points):
        raise RuntimeError("duplicate institution in production peer population")

    report: dict[str, Any] = {
        "sector": sector,
        "analysis_month": analysis_month,
        "population": len(points),
        "region_coverage": {
            "sido": sum(point.region_sido is not None for point in points),
            "sigungu": sum(point.region_sigungu is not None for point in points),
        },
        "region_sido_counts": dict(
            sorted(Counter(point.region_sido or "미확인" for point in points).items())
        ),
        "configs": {},
    }

    for target_peer_count in peer_counts:
        scope_counts: Counter[str] = Counter()
        fallback_counts: Counter[str] = Counter()
        candidate_counts: list[int] = []
        peer_count_values: list[int] = []
        insufficient = 0
        for target in points:
            selection = select_direct_funding_peers(
                points,
                target_institution_id=target.institution_id,
                sector=sector,
                selected_sido=target.region_sido,
                selected_sigungu=target.region_sigungu,
                target_peer_count=target_peer_count,
                minimum_peer_count=minimum_peer_count,
            )
            scope_counts[selection.selected_scope] += 1
            fallback_counts["fallback" if selection.fallback_used else "direct"] += 1
            candidate_counts.append(selection.candidate_count)
            peer_count_values.append(selection.peer_count)
            if selection.sample_status != "sufficient":
                insufficient += 1

        report["configs"][str(target_peer_count)] = {
            "target_peer_count": target_peer_count,
            "minimum_peer_count": minimum_peer_count,
            "direct_scope_count": fallback_counts["direct"],
            "fallback_count": fallback_counts["fallback"],
            "fallback_ratio": (
                fallback_counts["fallback"] / len(points) if points else None
            ),
            "insufficient_count": insufficient,
            "insufficient_ratio": insufficient / len(points) if points else None,
            "candidate_count": _summary(candidate_counts),
            "actual_peer_count": _summary(peer_count_values),
            "selected_scope_counts": dict(scope_counts.most_common()),
        }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--sector", default="nh_local")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--minimum-peer-count", type=int, default=8)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = calibrate(
        args.db,
        sector=args.sector,
        minimum_peer_count=args.minimum_peer_count,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
