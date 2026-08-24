#!/usr/bin/env python3
"""FINLIFE payment-method ambiguity의 이름/서비스 taxonomy를 fresh raw에서 감사한다.

대상은 B1 census에서 counterpart가 없었던 아산/진주 10건이다. 이 스크립트는
fresh FINLIFE `savingProductsSearch` raw와 fresh FSB raw를 읽어서 source가 실제로
보낸 product name/code/payment type과 반대편 상품 목록을 보존한다. DB/canonical은
읽거나 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from rate_monitor.services.institution_matching import normalize_institution

TARGETS = {
    "아산저축은행": "SB톡톡-정기예금",
    "진주저축은행": "정기예금(진주)",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_files(raw_root: Path, pattern: str) -> list[Path]:
    return sorted(path for path in raw_root.rglob(pattern) if path.is_file())


def _finlife_records(raw_root: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for path in _json_files(raw_root, "savingProductsSearch_030300_page*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            continue
        bases = result.get("baseList") or []
        options = result.get("optionList") or []
        option_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for option in options:
            if not isinstance(option, dict):
                continue
            key = (str(option.get("fin_co_no")), str(option.get("fin_prdt_cd")))
            option_map.setdefault(key, []).append(option)

        for base_index, base in enumerate(bases):
            if not isinstance(base, dict):
                continue
            institution = str(base.get("kor_co_nm") or "").strip()
            target_product = TARGETS.get(institution)
            if target_product is None or str(base.get("fin_prdt_nm") or "").strip() != target_product:
                continue
            key = (str(base.get("fin_co_no")), str(base.get("fin_prdt_cd")))
            matched_options = option_map.get(key, [])
            output.append(
                {
                    "source": "finlife_savings_bank",
                    "service": "savingProductsSearch",
                    "raw_path": str(path),
                    "raw_sha256": _sha256(path),
                    "base_index": base_index,
                    "institution": institution,
                    "fin_co_no": base.get("fin_co_no"),
                    "fin_prdt_cd": base.get("fin_prdt_cd"),
                    "fin_prdt_nm": base.get("fin_prdt_nm"),
                    "join_way": base.get("join_way"),
                    "dcls_month": base.get("dcls_month"),
                    "dcls_strt_day": base.get("dcls_strt_day"),
                    "dcls_end_day": base.get("dcls_end_day"),
                    "spcl_cnd": base.get("spcl_cnd"),
                    "etc_note": base.get("etc_note"),
                    "options": [
                        {
                            "save_trm": option.get("save_trm"),
                            "intr_rate_type": option.get("intr_rate_type"),
                            "intr_rate_type_nm": option.get("intr_rate_type_nm"),
                            "rsrv_type": option.get("rsrv_type"),
                            "rsrv_type_nm": option.get("rsrv_type_nm"),
                            "intr_rate": option.get("intr_rate"),
                            "intr_rate2": option.get("intr_rate2"),
                        }
                        for option in matched_options
                    ],
                }
            )
    return output


def _fsb_records(raw_root: Path) -> dict[str, Any]:
    target_norm = {normalize_institution(name): name for name in TARGETS}
    institution_records: dict[str, list[dict[str, Any]]] = {
        institution: [] for institution in TARGETS
    }
    for path in _json_files(raw_root, "rateinst_p*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("REC") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            continue
        file_sha = _sha256(path)
        for record in records:
            if not isinstance(record, dict):
                continue
            normalized = normalize_institution(record.get("BANK_NAME"))
            institution = target_norm.get(normalized)
            if institution is None:
                continue
            institution_records[institution].append(
                {
                    "raw_path": str(path),
                    "raw_sha256": file_sha,
                    "bank_name": str(record.get("BANK_NAME") or "").strip(),
                    "finan_comp_code": record.get("FINAN_COMP_CODE"),
                    "finan_prod_code": record.get("FINAN_PROD_CODE"),
                    "product_name": str(record.get("PRODUCT_NAME") or "").strip(),
                    "product_url": record.get("PRODUCT_URL"),
                    "start_date": record.get("START_DATE"),
                }
            )

    output: dict[str, Any] = {}
    for institution, records in institution_records.items():
        target_product = TARGETS[institution]
        exact = [record for record in records if record["product_name"] == target_product]
        output[institution] = {
            "target_product": target_product,
            "exact_target_records": exact,
            "all_products": sorted(
                {
                    (
                        record["product_name"],
                        str(record.get("finan_prod_code") or ""),
                        str(record.get("start_date") or ""),
                    )
                    for record in records
                }
            ),
            "record_count": len(records),
        }
    return output


def build_report(raw_root: Path) -> dict[str, Any]:
    finlife = _finlife_records(raw_root)
    fsb = _fsb_records(raw_root)

    by_target: list[dict[str, Any]] = []
    for institution, product in TARGETS.items():
        source_records = [
            record
            for record in finlife
            if record["institution"] == institution and record["fin_prdt_nm"] == product
        ]
        option_payment_methods = sorted(
            {
                str(option.get("rsrv_type") or "unknown").strip().upper()
                for record in source_records
                for option in record["options"]
            }
        )
        by_target.append(
            {
                "institution": institution,
                "product": product,
                "finlife_records": source_records,
                "finlife_product_codes": sorted(
                    {str(record.get("fin_prdt_cd") or "") for record in source_records}
                ),
                "finlife_option_count": sum(len(record["options"]) for record in source_records),
                "finlife_payment_methods": option_payment_methods,
                "fsb_exact_target_records": fsb[institution]["exact_target_records"],
                "fsb_all_products": fsb[institution]["all_products"],
                "fsb_record_count": fsb[institution]["record_count"],
            }
        )

    return {
        "scope": {
            "mode": "fresh_raw_read_only_taxonomy_forensic",
            "production_state_used": False,
            "production_state_mutated": False,
            "canonical_mutated": False,
            "source_precedence_changed": False,
            "authority_selected": False,
            "identity_changed": False,
        },
        "targets": by_target,
        "summary": {
            "target_count": len(by_target),
            "finlife_target_base_records": len(finlife),
            "targets_with_finlife_saving_service_record": sum(
                bool(item["finlife_records"]) for item in by_target
            ),
            "targets_with_fsb_exact_name_counterpart": sum(
                bool(item["fsb_exact_target_records"]) for item in by_target
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    report = build_report(args.raw_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    for target in report["targets"]:
        print(
            target["institution"],
            target["product"],
            "finlife_codes=", target["finlife_product_codes"],
            "payment_methods=", target["finlife_payment_methods"],
            "fsb_exact=", len(target["fsb_exact_target_records"]),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
