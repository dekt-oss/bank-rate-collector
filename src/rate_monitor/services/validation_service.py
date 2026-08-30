"""저장된 데이터가 계약을 지키는지 확인한다.

`scripts/verify_gate.py`는 배포 산출물 전체(스냅샷·manifest·대시보드)를 본다.
이쪽은 DB 하나만 보고 빨리 답한다. 수집 직후 손으로 확인할 때 쓴다.

검사는 전부 **실패할 수 있는 형태**로 쓴다. 항상 참인 검사는 검사가 아니다.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from rate_monitor.collectors.nh_local.resumable import NH_ACQUISITION_CONTRACT_MARKER


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _one(conn: sqlite3.Connection, sql: str) -> int:
    return conn.execute(sql).fetchone()[0]


def _nh_ejoy_current_run_checks(conn: sqlite3.Connection) -> list[Check]:
    """NH resumable v2의 e-joy evidence가 최고금리 관측까지 이어졌는지 본다.

    v1은 run message에 계약 표식이 없다. resumable v2는 fetch 완료 시
    ``nh_acquisition_contract=v2``를 남긴다. raw metadata 자체만으로 v2를
    판별하면 #255 때처럼 ``ejoy_options``가 통째로 사라진 회귀를 v1로 오인할
    수 있으므로, run 표식을 독립 기준으로 사용한다.

    한 번이라도 v2 confirmed run이 생긴 뒤 최신 confirmed NH run이 표식을 잃으면
    계약 회귀로 실패한다. 실패한 최신 attempt는 이전 정상값을 화면에 남기기 위해
    confirmed run 선택에서 제외한다.

    ``rate_observations``는 change-only 이력이므로 current run 대조는 ``run_id``가
    아니라 ``last_run_id``를 사용한다. 값이 이전과 같아 새 row가 생기지 않아도
    이번 run에서 실제로 재확인됐다면 검사를 통과해야 한다.
    """
    latest = conn.execute(
        "SELECT id, status, COALESCE(message, '') FROM collection_runs"
        " WHERE source_id = 'nh_local'"
        "   AND status IN ('success', 'partial', 'no_change')"
        " ORDER BY started_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if latest is None:
        return [
            Check(
                "[건너뜀] NH e-joy v2 current-run gate",
                True,
                "confirmed NH run이 없다",
            )
        ]

    ever_v2 = conn.execute(
        "SELECT COUNT(*) FROM collection_runs"
        " WHERE source_id = 'nh_local'"
        "   AND status IN ('success', 'partial', 'no_change')"
        "   AND message LIKE ?",
        (f"%{NH_ACQUISITION_CONTRACT_MARKER}%",),
    ).fetchone()[0]

    run_id, status, message = latest
    latest_is_v2 = NH_ACQUISITION_CONTRACT_MARKER in message
    if not latest_is_v2:
        if ever_v2:
            return [
                Check(
                    "NH e-joy v2 run contract 연속성",
                    False,
                    f"run {run_id} ({status})이 v2 전환 후 계약 표식을 잃었다",
                )
            ]
        return [
            Check(
                "[건너뜀] NH e-joy v2 current-run gate",
                True,
                f"run {run_id} ({status})은 v1 baseline",
            )
        ]

    rate_artifacts, v2_artifacts, evidence_artifacts = conn.execute(
        "SELECT COUNT(*),"
        " COALESCE(SUM(CASE"
        "   WHEN json_type(request_meta_json, '$.ejoy_options') = 'array' THEN 1"
        "   ELSE 0 END), 0),"
        " COALESCE(SUM(CASE"
        "   WHEN json_type(request_meta_json, '$.ejoy_options') = 'array'"
        "    AND COALESCE(json_array_length(request_meta_json, '$.ejoy_options'), 0) > 0"
        "   THEN 1 ELSE 0 END), 0)"
        " FROM raw_artifacts"
        " WHERE run_id = ?"
        "   AND json_extract(request_meta_json, '$.kind') = 'rate'",
        (run_id,),
    ).fetchone()

    current_max = conn.execute(
        "SELECT COUNT(*) FROM rate_observations"
        " WHERE last_run_id = ? AND max_rate IS NOT NULL",
        (run_id,),
    ).fetchone()[0]

    return [
        Check(
            "NH e-joy v2 run contract 표식",
            True,
            f"run {run_id} ({status})",
        ),
        Check(
            "NH e-joy v2 raw metadata 완결성",
            rate_artifacts > 0 and v2_artifacts == rate_artifacts,
            f"run {run_id}: v2 metadata {v2_artifacts}/{rate_artifacts} rate artifacts",
        ),
        Check(
            "NH e-joy evidence → current max_rate",
            evidence_artifacts == 0 or current_max > 0,
            f"run {run_id}: evidence artifacts {evidence_artifacts} / max_rate {current_max}건",
        ),
    ]


def run_validations(db_path: Path) -> list[Check]:
    conn = sqlite3.connect(db_path)
    try:
        checks: list[Check] = []

        observations = _one(conn, "SELECT COUNT(*) FROM rate_observations")
        checks.append(Check("관측이 있다", observations > 0, f"{observations}건"))

        orphan = _one(
            conn,
            "SELECT COUNT(*) FROM rate_observations WHERE raw_artifact_id IS NULL",
        )
        checks.append(Check("원본 추적 누락 0", orphan == 0, f"{orphan}건"))

        locator = _one(
            conn,
            "SELECT COUNT(*) FROM rate_observations"
            " WHERE base_source_locator IS NULL OR base_source_locator = ''"
            "    OR source_record_hash IS NULL OR source_record_hash = ''",
        )
        checks.append(Check("행 위치·해시 누락 0", locator == 0, f"{locator}건"))

        # 금리가 0 패딩 문자열이 아니면 정렬이 사전순으로 깨진다.
        malformed = _one(
            conn,
            "SELECT COUNT(*) FROM rate_observations"
            " WHERE base_rate IS NOT NULL AND base_rate NOT GLOB"
            " '[0-9][0-9][0-9].[0-9][0-9][0-9][0-9]'",
        )
        checks.append(Check("금리 저장 형식", malformed == 0, f"어긋난 값 {malformed}건"))

        # 새마을금고는 공식 화면에 우대금리 열이 없다. 채워지면 날조다.
        kfcc_max = _one(
            conn,
            "SELECT COUNT(*) FROM rate_observations o"
            "  JOIN collection_runs r ON r.id = o.run_id"
            " WHERE r.source_id = 'kfcc' AND o.max_rate IS NOT NULL",
        )
        checks.append(
            Check("새마을금고 최고금리 비어 있음", kfcc_max == 0, f"{kfcc_max}건")
        )

        # NH resumable v2는 TERM raw에서 공식 e-joy evidence를 복원해 같은 BRC의
        # 예금/적금 internet variant에 최고금리를 만든다. evidence가 있는데
        # current run의 max_rate가 0이면 #255 이전의 침묵 실패가 재발한 것이다.
        checks.extend(_nh_ejoy_current_run_checks(conn))

        # 저축은행 금리는 원천이 스스로 본점 기준이라고 밝힌 값이다. 화면에
        # 지점 금리로 나가면 안 되므로 저장 단계에서 못박는다.
        wrong_scope = _one(
            conn,
            "SELECT COUNT(*) FROM rate_observations o"
            "  JOIN collection_runs r ON r.id = o.run_id"
            "  JOIN product_variants v ON v.id = o.variant_id"
            " WHERE r.source_id IN ('fsb', 'finlife')"
            "   AND v.rate_scope NOT IN ('head_office_reference', 'nationwide')",
        )
        checks.append(
            Check("저축은행 금리는 본점 기준", wrong_scope == 0, f"{wrong_scope}건")
        )

        # 같은 비교단위를 한 실행에서 두 번 저장하면 이력이 어긋난다.
        dupes = _one(
            conn,
            "SELECT COUNT(*) FROM ("
            "  SELECT run_id, variant_id FROM rate_observations"
            "   GROUP BY run_id, variant_id HAVING COUNT(*) > 1)",
        )
        checks.append(Check("실행 내 관측 중복 0", dupes == 0, f"{dupes}건"))

        # 권역을 추측하면 "bank:1203" 같은 키가 생긴다.
        bad_sector = _one(
            conn,
            "SELECT COUNT(*) FROM source_entity_links"
            " WHERE entity_type = 'institution'"
            "   AND source_id = 'kfcc' AND source_entity_key NOT LIKE 'kfcc:%'",
        )
        checks.append(Check("새마을금고 기관키 권역", bad_sector == 0, f"{bad_sector}건"))

        # 화면 파라미터를 행정구역 공식 코드로 쓰면 안 된다.
        codes = _one(
            conn,
            "SELECT COUNT(*) FROM institutions"
            " WHERE sido_code IS NOT NULL OR sigungu_code IS NOT NULL",
        )
        checks.append(Check("행정구역 코드 미채움", codes == 0, f"{codes}건"))

        # 실패한 실행이 관측을 남기면 이전 정상값을 덮는다.
        failed_rows = _one(
            conn,
            "SELECT COUNT(*) FROM rate_observations o"
            "  JOIN collection_runs r ON r.id = o.run_id"
            " WHERE r.status IN ('failed', 'blocked', 'schema_changed')",
        )
        checks.append(Check("실패 실행의 관측 0", failed_rows == 0, f"{failed_rows}건"))

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        checks.append(Check("integrity_check", integrity == "ok", integrity))

        fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        checks.append(Check("foreign_key_check", fk == 0, f"{fk}건"))

        return checks
    finally:
        conn.close()
