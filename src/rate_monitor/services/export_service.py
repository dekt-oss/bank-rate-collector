"""전체 조사 내용 내보내기.

화면의 "CSV 내려받기"는 브라우저가 만든다. 이쪽은 같은 데이터를 파일로
뽑아 Artifact나 배포 산출물에 함께 싣는 경로다. 화면을 열지 않고도 받을 수
있어야 한다는 요구를 만족한다.

두 산출물은 **같은 열 정의**(`dashboard_service.TABLE_COLUMNS`)를 쓴다.
따로 관리하면 어느 쪽이 맞는지 알 수 없게 된다.
"""

import csv
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rate_monitor.services.dashboard_service import (
    DISTRICT_EXPR,
    TABLE_COLUMNS,
    build_rate_table,
    latest_run_ids,
)

# 사람이 여는 파일이므로 머리글을 한국어로 단다.
CSV_HEADERS = {
    "sector": "권역",
    "institution": "기관",
    "region": "시도",
    "district": "구·군",
    "product": "상품",
    "product_type": "상품유형",
    "term_months": "가입기간(개월)",
    "payment_method": "지급방식",
    "interest_method": "이자방식",
    "join_channel": "가입채널",
    "base_rate": "기본금리(%)",
    "max_rate": "최고금리(%)",
    "availability_scope": "가입제한",
    "source_id": "수집원",
    "source_effective_at": "공시기준일",
}

SECTOR_KO = {"savings_bank": "저축은행", "kfcc": "새마을금고", "bank": "은행"}
TYPE_KO = {
    "term_deposit": "예금",
    "installment_savings": "적금",
    "flexible_savings": "자유적립",
    "demand_deposit": "입출금",
    "other": "기타",
}
SCOPE_KO = {
    "workplace_members": "직장금고",
    "local_members": "지역금고",
    "nationwide": "전국",
    "unknown": "미상",
}


def expand(table: dict[str, Any]) -> list[dict[str, Any]]:
    """압축 배열을 사람이 읽는 행으로 되돌린다."""
    columns = table["columns"]
    lookups = table.get("lookups") or {}
    out: list[dict[str, Any]] = []
    for row in table["rows"]:
        record: dict[str, Any] = {}
        for index, name in enumerate(columns):
            value = row[index]
            if name in lookups:
                value = lookups[name][value]
            record[name] = value
        record["sector"] = SECTOR_KO.get(record["sector"], record["sector"])
        record["product_type"] = TYPE_KO.get(
            record["product_type"], record["product_type"]
        )
        record["availability_scope"] = SCOPE_KO.get(
            record["availability_scope"], record["availability_scope"]
        )
        out.append(record)
    return out


def export_dataset(
    db_path: Path, out_dir: Path, *, formats: tuple[str, ...] = ("csv", "json")
) -> list[Path]:
    """수집원별 마지막 실행의 관측 전체를 파일로 쓴다."""
    conn = sqlite3.connect(db_path)
    try:
        run_ids = latest_run_ids(conn)
        table = build_rate_table(conn, run_ids, DISTRICT_EXPR)
    finally:
        conn.close()

    records = expand(table)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    written: list[Path] = []

    if "csv" in formats:
        path = out_dir / f"rates_{stamp}.csv"
        # utf-8-sig — BOM이 없으면 엑셀이 한글을 깨서 연다.
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([CSV_HEADERS[c] for c in TABLE_COLUMNS])
            for record in records:
                writer.writerow([record.get(c) for c in TABLE_COLUMNS])
        written.append(path)

    if "json" in formats:
        path = out_dir / f"rates_{stamp}.json"
        path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(UTC).isoformat(),
                    "columns": list(TABLE_COLUMNS),
                    "count": len(records),
                    "records": records,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        written.append(path)

    return written
