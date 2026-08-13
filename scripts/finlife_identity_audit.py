"""FINLIFE 서비스 경계와 저장된 상품유형의 일치 여부를 감사한다.

FINLIFE의 ``fin_prdt_cd``는 depositProductsSearch / savingProductsSearch 사이에서
재사용될 수 있다. 최신 확인 실행의 observation이 어느 raw service에서 왔는지와
연결된 Product.product_type이 맞는지 검사해 cross-service identity 오염을 잡는다.

읽기 전용이다. DB를 수정하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

CONFIRMED_RUN_STATUSES = ("success", "partial", "no_change")
SERVICE_PRODUCT_TYPE = {
    "depositProductsSearch": "term_deposit",
    "savingProductsSearch": "installment_savings",
}


def _service_from_path(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    name = Path(relative_path).name
    for service in SERVICE_PRODUCT_TYPE:
        if name.startswith(f"{service}_") or name == f"{service}.json":
            return service
    return None


def _latest_confirmed_run(conn: sqlite3.Connection, source_id: str) -> str | None:
    placeholders = ",".join("?" for _ in CONFIRMED_RUN_STATUSES)
    row = conn.execute(
        "SELECT id FROM collection_runs "
        "WHERE source_id = ? "
        f"AND status IN ({placeholders}) "
        "ORDER BY started_at DESC LIMIT 1",
        (source_id, *CONFIRMED_RUN_STATUSES),
    ).fetchone()
    return str(row[0]) if row else None


def audit_finlife_identity(
    db_path: Path,
    *,
    source_id: str = "finlife_savings_bank",
) -> dict[str, Any]:
    """최신 확인 실행의 FINLIFE raw service ↔ product_type 불일치를 반환한다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        run_id = _latest_confirmed_run(conn, source_id)
        if run_id is None:
            return {
                "source_id": source_id,
                "latest_run_id": None,
                "checked": 0,
                "unknown_service": 0,
                "mismatch_count": 0,
                "mismatches": [],
            }

        rows = conn.execute(
            "SELECT o.id AS observation_id, o.last_run_id, "
            "       p.id AS product_id, p.name AS product_name, "
            "       p.product_type, pv.id AS variant_id, "
            "       ra.relative_path AS raw_artifact_path, "
            "       o.base_source_locator, o.option_source_locator "
            "FROM rate_observations o "
            "JOIN product_variants pv ON pv.id = o.variant_id "
            "JOIN products p ON p.id = pv.product_id "
            "JOIN raw_artifacts ra ON ra.id = o.raw_artifact_id "
            "WHERE o.last_run_id = ? "
            "ORDER BY p.name, pv.id, o.id",
            (run_id,),
        ).fetchall()

        mismatches: list[dict[str, Any]] = []
        unknown_service = 0
        for row in rows:
            service = _service_from_path(row["raw_artifact_path"])
            if service is None:
                unknown_service += 1
                continue
            expected = SERVICE_PRODUCT_TYPE[service]
            actual = row["product_type"]
            if actual == expected:
                continue
            mismatches.append(
                {
                    "observation_id": row["observation_id"],
                    "product_id": row["product_id"],
                    "variant_id": row["variant_id"],
                    "product_name": row["product_name"],
                    "actual_product_type": actual,
                    "expected_product_type": expected,
                    "service": service,
                    "raw_artifact_path": row["raw_artifact_path"],
                    "base_source_locator": row["base_source_locator"],
                    "option_source_locator": row["option_source_locator"],
                }
            )

        return {
            "source_id": source_id,
            "latest_run_id": run_id,
            "checked": len(rows),
            "unknown_service": unknown_service,
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--source", default="finlife_savings_bank")
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--allow-mismatch",
        action="store_true",
        help="진단용: 불일치를 출력하되 exit 1로 실패시키지 않는다.",
    )
    args = parser.parse_args()

    report = audit_finlife_identity(args.db, source_id=args.source)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")

    if report["latest_run_id"] is None:
        return 2
    if report["unknown_service"]:
        return 3
    if report["mismatch_count"] and not args.allow_mismatch:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
