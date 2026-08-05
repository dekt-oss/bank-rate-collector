"""저장된 데이터가 계약을 지키는지 확인한다.

`scripts/verify_gate.py`는 배포 산출물 전체(스냅샷·manifest·대시보드)를 본다.
이쪽은 DB 하나만 보고 빨리 답한다. 수집 직후 손으로 확인할 때 쓴다.

검사는 전부 **실패할 수 있는 형태**로 쓴다. 항상 참인 검사는 검사가 아니다.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _one(conn: sqlite3.Connection, sql: str) -> int:
    return conn.execute(sql).fetchone()[0]


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
