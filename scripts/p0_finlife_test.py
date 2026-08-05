#!/usr/bin/env python3
"""P0: 금융감독원 finlife 정기예금 API 망분리·인증 테스트.

원본 관측값을 그대로 보존한다는 명세서 v2 원칙에 따라 응답 JSON을
그대로 data/raw/p0/finlife/ 아래에 저장하고, 요약만 표준출력에 남긴다.

사용법:
    FINLIFE_API_KEY=... python scripts/p0_finlife_test.py [topFinGrpNo]

topFinGrpNo 기본값은 030300(저축은행). 은행 020000 등으로 바꿔 재실행 가능.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "http://finlife.fss.or.kr/finlifeapi/depositProductsSearch.json"
RAW_DIR = Path("data/raw/p0/finlife")


def fetch_page(auth: str, top_fin_grp_no: str, page_no: int) -> dict:
    query = (
        f"?auth={auth}"
        f"&topFinGrpNo={top_fin_grp_no}"
        f"&pageNo={page_no}"
    )
    req = urllib.request.Request(API_URL + query, headers={"User-Agent": "rate-monitor-p0/1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    auth = os.environ.get("FINLIFE_API_KEY")
    if not auth:
        print("FINLIFE_API_KEY 환경변수가 없습니다.", file=sys.stderr)
        return 1

    top_fin_grp_no = sys.argv[1] if len(sys.argv) > 1 else "030300"
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    page_no = 1
    total_companies = 0
    total_options = 0
    while True:
        try:
            data = fetch_page(auth, top_fin_grp_no, page_no)
        except urllib.error.URLError as exc:
            print(f"네트워크 오류(망분리 의심): {exc}", file=sys.stderr)
            return 1

        result = data.get("result", {})
        err_cd = result.get("err_cd")
        if err_cd not in (None, "000"):
            print(f"API 오류: err_cd={err_cd} err_msg={result.get('err_msg')}", file=sys.stderr)
            return 1

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = RAW_DIR / f"{top_fin_grp_no}_page{page_no}_{stamp}.json"
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        base_list = result.get("baseList", [])
        option_list = result.get("optionList", [])
        total_companies += len(base_list)
        total_options += len(option_list)

        max_page_no = result.get("max_page_no", page_no)
        now_page_no = result.get("now_page_no", page_no)
        print(
            f"page {now_page_no}/{max_page_no}: "
            f"companies={len(base_list)} options={len(option_list)} -> {out_path}"
        )

        if now_page_no >= max_page_no:
            break
        page_no += 1

    print(f"완료: topFinGrpNo={top_fin_grp_no} total_companies={total_companies} total_options={total_options}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
