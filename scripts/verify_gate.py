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
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))


def _workspace_run_context(
    conn: sqlite3.Connection, raw_root: Path
) -> tuple[list[Path], list[tuple[str, str, str]], list[str]]:
    """현재 러너 디스크의 원본을 DB collection run과 연결한다.

    ``data/raw/<날짜>/<run_id>/<파일>``은 collection_service가 만드는 계약이다.
    복원된 DB에는 과거 run이 모두 있지만 러너 디스크에는 **이번 실행에서 받은
    원본만** 있으므로, 이 디렉터리의 run_id가 current-run gate의 경계가 된다.

    반환값은 (현재 원본 파일, DB에서 찾은 run, DB에 없는 run_id)다.
    """
    files = sorted(p for p in raw_root.rglob("*") if p.is_file()) if raw_root.exists() else []
    run_ids = sorted({p.parent.name for p in files})
    if not run_ids:
        return files, [], []

    marks = ",".join("?" for _ in run_ids)
    rows = conn.execute(
        f"SELECT id, source_id, status FROM collection_runs WHERE id IN ({marks})",
        run_ids,
    ).fetchall()
    found = {row[0] for row in rows}
    missing = sorted(set(run_ids) - found)
    return files, rows, missing


def _finlife_source_missing(files: list[Path]) -> tuple[int, int]:
    """현재 finlife 원본에서 intr_rate2 결측을 센다.

    원본 디렉터리에는 JSON 형식이 다른 수집원도 함께 있으므로 finlife의
    ``result.optionList`` 모양인 파일만 센다.
    """
    source_missing = 0
    finlife_files = 0
    for raw_file in files:
        if raw_file.suffix.lower() != ".json":
            continue
        payload = json.loads(raw_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        result = payload.get("result")
        if not isinstance(result, dict) or "optionList" not in result:
            continue
        finlife_files += 1
        options = result.get("optionList") or []
        source_missing += sum(1 for o in options if o.get("intr_rate2") is None)
    return finlife_files, source_missing


def _finlife_observation_nulls(
    conn: sqlite3.Connection, run_ids: list[str]
) -> tuple[int, int]:
    """이번 finlife run이 마지막으로 확인한 현재 관측의 NULL을 센다.

    rate_observations는 change-only 이력이다. ``run_id``는 값을 처음 본 실행이고
    ``last_run_id``가 그 값을 마지막으로 확인한 실행이므로 current-run 대조는
    반드시 ``last_run_id``를 사용한다.
    """
    if not run_ids:
        return 0, 0
    marks = ",".join("?" for _ in run_ids)
    return conn.execute(
        "SELECT COUNT(*), COUNT(*) - COUNT(max_rate) FROM rate_observations "
        f"WHERE last_run_id IN ({marks})",
        run_ids,
    ).fetchone()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    # 수집을 건너뛴 실행인가 (v3.1 §12.4).
    #
    # 이 게이트는 "방금 수집했다"는 전제로 쓰였다. 발행만 하는 실행에는
    # 러너 디스크에 원본이 없다 — 사라진 게 아니라 안 만든 것이다. 그걸
    # 실패로 세면 머지해도 화면이 안 바뀐다 (run 25·26이 그랬다).
    parser.add_argument(
        "--no-collection",
        action="store_true",
        help="이번 실행은 수집을 하지 않았다. 원본 파일을 보는 항목을 건너뛴다",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        )
    ]
    # 개수가 아니라 **모델과 같은 것들인가**를 묻는다.
    #
    # 예전에는 `len(tables) == 13`이었다. 표를 하나 더하면 스키마가 맞는데도
    # 여기서 죽는다 — 2026-08-06 run 31084088559이 그렇게 발행 직전에 멈췄고,
    # 정작 무엇이 다른지는 알려 주지 않았다. 이제 없는 것과 더 있는 것을
    # 이름으로 말한다.
    #
    # extension 모델은 models.py 밖에서 같은 Base registry에 표를 추가한다.
    # 정적 ALL_TABLES는 해당 모듈 import 시점에 고정되므로 새 extension 표를
    # 놓칠 수 있다. 모든 extension을 등록한 뒤 살아있는 metadata를 기준으로 본다.
    import rate_monitor.db.institution_funding_models  # noqa: F401
    from rate_monitor.db.models import Base

    expected_tables = set(Base.metadata.tables)
    missing = sorted(expected_tables - set(tables))
    extra = sorted(set(tables) - expected_tables)
    detail = f"{len(tables)}종, 모델과 일치"
    if missing or extra:
        detail = f"없음 {missing} / 더 있음 {extra}"
    check(not missing and not extra, "SQLite 표가 모델과 같은가", detail)

    observations = conn.execute("SELECT COUNT(*) FROM rate_observations").fetchone()[0]
    check(observations > 0, "실제 데이터 수집", f"관측 {observations}건")

    # ── Current Run Gate ───────────────────────────────────────────────
    #
    # 복원한 DB에는 과거 원천이 전부 들어 있지만 data/raw에는 이번 workflow가
    # 실제로 받은 원본만 있다. 둘을 섞으면 KFCC-only 실행이 과거 finlife
    # 관측의 원본까지 현재 디스크에서 찾다가 실패한다 (2026-08-10 run 45).
    # 현재 raw 디렉터리의 run_id를 DB에 되짚어 이번 실행의 경계를 정한다.
    workspace_files, workspace_runs, unknown_workspace_runs = _workspace_run_context(
        conn, args.raw_root
    )
    raw_files = [p for p in workspace_files if p.suffix.lower() == ".json"]
    raw_html = [p for p in workspace_files if p.suffix.lower() == ".html"]

    if args.no_collection:
        check(True, "[건너뜀] 원본 보존", "이번 실행은 수집을 하지 않았다")
        check(
            len(workspace_files) == 0,
            "Current Run 원본 경계",
            f"발행 전용 실행의 원본 {len(workspace_files)}개",
        )
    else:
        check(
            len(workspace_files) > 0,
            "원본 보존",
            f"JSON {len(raw_files)}개 / HTML {len(raw_html)}개",
        )
        check(
            not unknown_workspace_runs,
            "Current Run 원본 run_id ↔ collection_runs 연결",
            "모두 연결" if not unknown_workspace_runs else f"DB에 없음 {unknown_workspace_runs}",
        )

    # ── Historical Integrity Gate ──────────────────────────────────────
    #
    # 아래 provenance 검사는 현재 러너 파일 유무와 무관하게 canonical DB 전체에
    # 적용한다. current-run raw semantic check와 historical DB integrity를
    # 분리하되 검증 강도는 낮추지 않는다.
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

    # max_rate NULL 규칙: 원본에 우대금리가 없으면 저장값도 NULL이어야 한다.
    # base_rate로 메우면 안 된다 (명세서 v3 §8.4).
    #
    # finlife 원본 대조는 **이번 실행에서 실제로 finlife를 수집한 run**만 본다.
    # rate_observations는 change-only이므로 run_id가 아니라 last_run_id로 현재
    # 확인된 값을 고른다. KFCC-only 같은 부분 수집에서 과거 finlife 관측을
    # 현재 KFCC 원본과 대조하지 않는다.
    from rate_monitor.services.dashboard_service import CONFIRMED_RUN_STATUSES

    confirmed_statuses = set(CONFIRMED_RUN_STATUSES)
    current_finlife_run_ids = sorted(
        run_id
        for run_id, source_id, status in workspace_runs
        if source_id.startswith("finlife") and status in confirmed_statuses
    )
    current_finlife_files = [
        p for p in workspace_files if p.parent.name in current_finlife_run_ids
    ]
    finlife_files, source_missing = _finlife_source_missing(current_finlife_files)
    finlife_rows, finlife_null = _finlife_observation_nulls(conn, current_finlife_run_ids)

    if args.no_collection:
        check(
            True,
            "[건너뜀] max_rate 대조용 finlife 원본 확보",
            "이번 실행은 수집을 하지 않았다",
        )
        check(
            True,
            "[건너뜀] max_rate NULL 규칙 — finlife (원본 대조)",
            "대조할 원본이 이번 실행에 없다",
        )
    elif not current_finlife_run_ids:
        check(
            True,
            "[건너뜀] max_rate 대조용 finlife 원본 확보",
            "이번 실행에서 finlife를 수집하지 않았다",
        )
        check(
            True,
            "[건너뜀] max_rate NULL 규칙 — finlife (원본 대조)",
            "이번 실행의 finlife run이 없다",
        )
    else:
        check(
            finlife_files > 0,
            "max_rate 대조용 finlife 원본 확보",
            f"현재 run {len(current_finlife_run_ids)}개 / 원본 {finlife_files}개",
        )
        check(
            finlife_null == source_missing,
            "max_rate NULL 규칙 — finlife (현재 run 원본 대조)",
            f"현재 관측 NULL {finlife_null}/{finlife_rows}건 == 원본 결측 {source_missing}건",
        )

    # ── 원천별 계약 검사 (v4 §5.8·§6.5) ────────────────────────────
    #
    # **어댑터가 자기 계약을 밝히고 게이트가 그걸 읽는다.**
    #
    # 예전에는 여기 원천 이름을 손으로 적었다 — `("kfcc", "새마을금고")`,
    # `("nh_local", "농·축협")` 같은 목록이 세 군데 흩어져 있었다. 원천을
    # 하나 더할 때마다 이 파일을 고쳐야 하고, 잊으면 그 원천은 아무 검사도
    # 안 받은 채 발행된다. 이제 어댑터를 더하면 검사도 같이 는다.
    from rate_monitor.cli import ADAPTERS

    for source_id, adapter_cls in sorted(ADAPTERS.items()):
        total = conn.execute(
            "SELECT COUNT(*) FROM rate_observations o"
            "  JOIN collection_runs r ON r.id = o.run_id"
            " WHERE r.source_id = ?",
            (source_id,),
        ).fetchone()[0]
        if total == 0:
            # 안 돌린 원천은 검사하지 않는다. 0 == 0으로 통과시키면 검사가
            # 아니라 장식이 된다 — 그 사실만 적어 둔다.
            check(True, f"[건너뜀] {source_id} — 관측 0건", "이번 DB에 없다")
            continue

        # 우대금리 열이 없는 원천은 저장값도 전부 NULL이어야 한다 (v3 §8.4).
        if not getattr(adapter_cls, "provides_max_rate", True):
            filled = conn.execute(
                "SELECT COUNT(o.max_rate) FROM rate_observations o"
                "  JOIN collection_runs r ON r.id = o.run_id"
                " WHERE r.source_id = ?",
                (source_id,),
            ).fetchone()[0]
            check(
                filled == 0,
                f"max_rate NULL 규칙 — {source_id} (원천이 우대금리를 안 준다)",
                f"관측 {total}건 중 채워진 값 {filled}건",
            )

        # 업권이 섞이면 화면이 둘을 못 가른다.
        wrong_sector = conn.execute(
            "SELECT COUNT(*) FROM rate_observations o"
            "  JOIN collection_runs r  ON r.id = o.run_id"
            "  JOIN product_variants v ON v.id = o.variant_id"
            "  JOIN products p         ON p.id = v.product_id"
            "  JOIN institutions i     ON i.id = p.institution_id"
            " WHERE r.source_id = ? AND i.sector <> ?",
            (source_id, adapter_cls.sector),
        ).fetchone()[0]
        check(
            wrong_sector == 0,
            f"업권 혼합 0 — {source_id} (sector={adapter_cls.sector})",
            f"관측 {total}건 중 어긋남 {wrong_sector}건",
        )

        # 금리 적용범위가 고정된 원천만 검사한다. 원천에 따라 갈리는 곳은
        # 기대값을 안 적어 뒀다 — 없는 규칙을 지어내지 않는다.
        expected_scope = getattr(adapter_cls, "expected_rate_scope", None)
        if expected_scope:
            wrong_scope = conn.execute(
                "SELECT COUNT(*) FROM rate_observations o"
                "  JOIN collection_runs r  ON r.id = o.run_id"
                "  JOIN product_variants v ON v.id = o.variant_id"
                " WHERE r.source_id = ? AND v.rate_scope <> ?",
                (source_id, expected_scope),
            ).fetchone()[0]
            check(
                wrong_scope == 0,
                f"rate_scope={expected_scope} — {source_id}",
                f"어긋난 행 {wrong_scope}건",
            )

    # 옛 이름이 남아 있으면 마이그레이션이 안 돈 것이다.
    legacy = conn.execute(
        "SELECT COUNT(*) FROM collection_runs WHERE source_id = 'finlife'"
    ).fetchone()[0]
    check(legacy == 0, "옛 finlife source_id 잔존 0", f"{legacy}건")

    # 마지막 수집이 실패한 원천. 화면은 직전 값을 보여주지만 그 사실이
    # 발행 로그에도 남아야 한다 — 조용히 어제 값을 내보내면 안 된다.
    marks = ",".join("?" for _ in CONFIRMED_RUN_STATUSES)
    stale = conn.execute(
        "SELECT last.source_id, last.status FROM ("
        "  SELECT r.* FROM collection_runs r"
        "    JOIN (SELECT source_id, MAX(started_at) AS started_at"
        "            FROM collection_runs GROUP BY source_id) m"
        "      ON m.source_id = r.source_id AND m.started_at = r.started_at) last"
        f" WHERE last.status NOT IN ({marks})",
        CONFIRMED_RUN_STATUSES,
    ).fetchall()
    # 막지는 않는다. 한 원천이 실패해도 나머지를 발행하는 편이 낫다.
    check(
        True,
        "마지막 수집이 실패한 원천",
        ", ".join(f"{s}({st})" for s, st in stale) if stale else "없음",
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
        site_html[
            start + len('<script id="rate-monitor-data" type="application/json">') : end
        ].replace("<\\/", "</")
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
