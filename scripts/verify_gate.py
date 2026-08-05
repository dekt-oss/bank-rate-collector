#!/usr/bin/env python3
"""P1-A 완료 게이트 검증 (명세서 v3.1 §12.1).

수집 워크플로우가 실제로 만든 산출물을 검사한다. 항목마다 통과/실패를
찍고, 하나라도 실패하면 0이 아닌 코드로 끝난다.

사용법:
    python scripts/verify_gate.py --db publish/rate_monitor.sqlite3 \
        --manifest publish/manifest.json --summary publish/summary.json \
        --site site/index.html --raw-root data/raw
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

EXPECTED_TABLE_COUNT = 13
results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        )
    ]
    check(len(tables) == EXPECTED_TABLE_COUNT, "SQLite 테이블 13종", f"{len(tables)}종")

    observations = conn.execute("SELECT COUNT(*) FROM rate_observations").fetchone()[0]
    check(observations > 0, "finlife 실제 데이터 수집", f"관측 {observations}건")

    raw_files = list(args.raw_root.rglob("*.json")) if args.raw_root.exists() else []
    check(len(raw_files) > 0, "원본 JSON 보존", f"{len(raw_files)}개 파일")

    missing_artifact = conn.execute(
        "SELECT COUNT(*) FROM rate_observations WHERE raw_artifact_id IS NULL"
    ).fetchone()[0]
    check(missing_artifact == 0, "원본 추적 raw_artifact_id 누락 0", f"{missing_artifact}건")

    missing_locator = conn.execute(
        "SELECT COUNT(*) FROM rate_observations "
        "WHERE base_source_locator IS NULL OR base_source_locator = '' "
        "   OR source_record_hash IS NULL OR source_record_hash = ''"
    ).fetchone()[0]
    check(missing_locator == 0, "원본 추적 locator 누락 0", f"{missing_locator}건")

    # max_rate NULL 규칙: 원본에 intr_rate2가 없으면 저장값도 NULL이어야 한다.
    # base_rate로 메우면 안 된다 (명세서 v3 §8.4).
    # 원본이 보존돼 있으므로 실제로 대조한다.
    source_missing = 0
    for raw_file in raw_files:
        payload = json.loads(raw_file.read_text(encoding="utf-8"))
        options = (payload.get("result") or {}).get("optionList") or []
        source_missing += sum(1 for o in options if o.get("intr_rate2") is None)
    stored_null = conn.execute(
        "SELECT COUNT(*) FROM rate_observations WHERE max_rate IS NULL"
    ).fetchone()[0]
    check(
        stored_null == source_missing,
        "max_rate NULL 규칙 (원본 대조)",
        f"저장 NULL {stored_null}건 == 원본 결측 {source_missing}건",
    )

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    check(integrity == "ok", "PRAGMA integrity_check", integrity)

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    check(len(violations) == 0, "PRAGMA foreign_key_check", f"{len(violations)}건")

    dup = conn.execute(
        "SELECT COUNT(*) FROM (SELECT variant_id, run_id FROM rate_observations "
        "GROUP BY variant_id, run_id HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    check(dup == 0, "동일 실행 내 관측 중복 0", f"{dup}건")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    import hashlib

    digest = hashlib.sha256()
    with args.db.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    check(
        digest.hexdigest() == manifest["sqlite_sha256"],
        "manifest SHA256 == 실제 DB 해시",
        manifest["sqlite_sha256"][:16],
    )

    counts_ok = all(
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected
        for table, expected in manifest["row_counts"].items()
    )
    check(counts_ok, "manifest 행 수 == SQL COUNT", str(manifest["row_counts"]))

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    site_html = args.site.read_text(encoding="utf-8")
    start = site_html.find('<script id="rate-monitor-data" type="application/json">')
    end = site_html.find("</script>", start)
    inline = json.loads(
        site_html[start + len('<script id="rate-monitor-data" type="application/json">') : end]
        .replace("<\\/", "</")
    )
    check(
        inline["totals"] == summary["totals"],
        "대시보드 표시 수치 == summary.json",
        str(summary["totals"]),
    )

    leaked = conn.execute(
        "SELECT COUNT(*) FROM raw_artifacts WHERE request_meta_json LIKE '%auth%' "
        "AND request_meta_json NOT LIKE '%REDACTED%'"
    ).fetchone()[0]
    check(leaked == 0, "FINLIFE_API_KEY 노출 0", f"{leaked}건")

    conn.close()

    print("\nP1-A 완료 게이트\n" + "=" * 52)
    for ok, name, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    failed = [r for r in results if not r[0]]
    print("=" * 52)
    print(f"  {len(results) - len(failed)}/{len(results)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
