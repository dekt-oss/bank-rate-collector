#!/usr/bin/env python3
"""P0: 금융감독원 finlife 오픈API 수집 가능 범위 검증.

명세서 v3의 미확정 항목을 실제 응답으로 판정한다.

1. 권역별(은행/저축은행) 정기예금·적금 API가 모두 수집되는가
2. 상품(baseList)·옵션(optionList)이 공식 키로 결합되는가
3. 지역 정보가 어디까지 제공되는가 — 부산 구 단위 필터가 finlife만으로 가능한가
4. 우대금리(intr_rate2)와 우대조건(spcl_cnd) 원문이 실제로 채워지는가

원본 응답은 data/raw/p0/finlife/ 에 그대로 보존하고, 판정 결과는
docs/source-recon/finlife-verify.json 으로 요약한다.

사용법:
    FINLIFE_API_KEY=... python scripts/p0_finlife_verify.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://finlife.fss.or.kr/finlifeapi"
RAW_DIR = Path("data/raw/p0/finlife")
REPORT_PATH = Path("docs/source-recon/finlife-verify.json")

# 권역코드: 020000=은행, 030300=저축은행
GROUPS = {"020000": "은행", "030300": "저축은행"}
# 서비스명: 상품 종류별 엔드포인트
SERVICES = {
    "depositProductsSearch": "정기예금",
    "savingProductsSearch": "적금",
    "companySearch": "금융회사",
}


def call(service: str, auth: str, top_fin_grp_no: str, page_no: int) -> dict:
    url = (
        f"{BASE}/{service}.json"
        f"?auth={auth}&topFinGrpNo={top_fin_grp_no}&pageNo={page_no}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "rate-monitor-p0/1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect_all(service: str, auth: str, top_fin_grp_no: str) -> tuple[dict, list, list]:
    """페이지 끝까지 순회해 baseList/optionList를 모은다."""
    base_rows: list[dict] = []
    option_rows: list[dict] = []
    meta: dict = {}
    page_no = 1
    while True:
        data = call(service, auth, top_fin_grp_no, page_no)
        result = data.get("result", {})
        err_cd = result.get("err_cd")
        if err_cd not in (None, "000"):
            raise RuntimeError(f"{service}/{top_fin_grp_no} err_cd={err_cd} {result.get('err_msg')}")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = RAW_DIR / f"{service}_{top_fin_grp_no}_page{page_no}_{stamp}.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        base_rows.extend(result.get("baseList", []))
        option_rows.extend(result.get("optionList", []))
        meta = {
            "total_count": result.get("total_count"),
            "max_page_no": result.get("max_page_no"),
        }

        now = int(result.get("now_page_no", page_no))
        mx = int(result.get("max_page_no", page_no))
        if now >= mx:
            break
        page_no += 1
        time.sleep(1.0)  # 명세서의 request_interval_seconds: 1.0 준수
    return meta, base_rows, option_rows


def main() -> int:
    auth = os.environ.get("FINLIFE_API_KEY")
    if not auth:
        print("FINLIFE_API_KEY 환경변수가 없습니다.", file=sys.stderr)
        return 1

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report: dict = {"checked_at": datetime.now(timezone.utc).isoformat(), "findings": {}}

    for grp, grp_name in GROUPS.items():
        for service, svc_name in SERVICES.items():
            key = f"{service}/{grp}"
            try:
                meta, base_rows, option_rows = collect_all(service, auth, grp)
            except (urllib.error.URLError, RuntimeError) as exc:
                print(f"[FAIL] {svc_name}/{grp_name}: {exc}")
                report["findings"][key] = {"ok": False, "error": str(exc)}
                continue

            entry: dict = {
                "ok": True,
                "group_name": grp_name,
                "service_name": svc_name,
                "total_count": meta.get("total_count"),
                "max_page_no": meta.get("max_page_no"),
                "base_count": len(base_rows),
                "option_count": len(option_rows),
                "base_fields": sorted(base_rows[0].keys()) if base_rows else [],
                "option_fields": sorted(option_rows[0].keys()) if option_rows else [],
            }

            if service == "companySearch":
                # 지역 정보: optionList의 area_cd/area_nm 이 점포 소재 지역을 나타낸다
                areas = Counter(
                    r.get("area_nm") for r in option_rows if r.get("exis_yn") == "Y"
                )
                busan = [
                    r for r in option_rows
                    if r.get("area_nm") and "부산" in str(r.get("area_nm"))
                    and r.get("exis_yn") == "Y"
                ]
                entry["area_names"] = sorted(a for a in areas if a)
                entry["busan_company_count"] = len({r.get("fin_co_no") for r in busan})
                entry["area_granularity"] = (
                    "시도" if all(len(str(a)) <= 4 for a in areas if a) else "확인필요"
                )
            else:
                # 상품·옵션 결합 키 확인
                base_keys = {(r.get("fin_co_no"), r.get("fin_prdt_cd")) for r in base_rows}
                opt_keys = {(r.get("fin_co_no"), r.get("fin_prdt_cd")) for r in option_rows}
                entry["join_key"] = "fin_co_no + fin_prdt_cd"
                entry["base_key_count"] = len(base_keys)
                entry["option_key_count"] = len(opt_keys)
                entry["orphan_option_keys"] = len(opt_keys - base_keys)
                entry["base_without_option"] = len(base_keys - opt_keys)

                # 우대금리·우대조건이 실제로 채워지는가
                has_intr2 = sum(
                    1 for r in option_rows
                    if r.get("intr_rate2") not in (None, "", "null")
                )
                entry["option_with_max_rate"] = has_intr2
                spcl = [r.get("spcl_cnd") for r in base_rows]
                entry["base_with_pref_text"] = sum(
                    1 for s in spcl if s and str(s).strip() not in ("", "-", "없음")
                )
                entry["pref_text_sample"] = next(
                    (str(s)[:120] for s in spcl if s and len(str(s).strip()) > 10), ""
                )
                # 지역 필드 존재 여부 — 부산 구 단위 필터 가능성 판정의 핵심
                region_like = [
                    f for f in entry["base_fields"] + entry["option_fields"]
                    if any(t in f for t in ("area", "region", "sido", "addr", "zone"))
                ]
                entry["region_fields_in_product_api"] = region_like

            report["findings"][key] = entry
            print(
                f"[OK] {svc_name}/{grp_name}: base={entry['base_count']} "
                f"option={entry['option_count']} total={entry['total_count']}"
            )
            time.sleep(1.0)

    # 종합 판정
    prod_keys = [k for k in report["findings"] if not k.startswith("companySearch")]
    has_region_in_product = any(
        report["findings"][k].get("region_fields_in_product_api")
        for k in prod_keys
        if report["findings"][k].get("ok")
    )
    company = report["findings"].get("companySearch/030300", {})
    report["conclusion"] = {
        "product_api_has_region_field": has_region_in_product,
        "busan_gu_filter_possible_from_finlife_alone": False if not has_region_in_product else "재검토",
        "company_api_area_granularity": company.get("area_granularity"),
        "note": (
            "상품 API는 지역 필드가 없고 전국(본점) 기준 공시다. "
            "금융회사 API의 area_cd/area_nm은 점포 소재 '시도' 단위이므로 "
            "부산 구·군 단위 필터는 finlife만으로 불가능하며, "
            "저축은행중앙회·새마을금고·신협 등 권역별 소스가 필요하다."
        ),
    }

    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n판정 요약 -> {REPORT_PATH}")
    print(json.dumps(report["conclusion"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
