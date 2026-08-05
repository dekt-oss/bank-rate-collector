"""금융감독원 finlife 오픈API 어댑터.

fetch()만 담당한다. 파싱은 parser.parse(), 저장은 오케스트레이터가 한다
(명세서 v3 §6.2).

요청 흐름은 scripts/p0_finlife_verify.py에서 2026-08-05에 실행 검증된 것을
옮겼다. 페이지 끝까지 순회(now_page_no >= max_page_no), err_cd 검사,
1.0초 요청 간격.
"""

import asyncio
import json
import os
from typing import Any

import httpx

from rate_monitor.collectors.base import (
    CollectorError,
    ParseError,
    SourceBlockedError,
    mask_auth_in_meta,
)
from rate_monitor.collectors.finlife import parser
from rate_monitor.domain.enums import CollectionMode, Sector, SourceRole, TrustLevel
from rate_monitor.domain.schemas import CollectionRequest, ParsedRateRow, RawArtifactData

# 2026-08-05 실측: http로 요청하면 서버가 307로 https에 리다이렉트한다.
# 공식 문서는 http를 안내하지만 실제 종단점은 https다. 평문으로 인증키를
# 보내지 않도록 처음부터 https로 요청한다.
BASE_URL = "https://finlife.fss.or.kr/finlifeapi"
API_KEY_ENV = "FINLIFE_API_KEY"

# 명세서 v3.1 §9 / v3 §15.3 request_interval_seconds
REQUEST_INTERVAL_SECONDS = 1.0
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 20.0
MAX_PAGES = 200  # 무한 순회 방지. 실측 최대 4페이지.


class FinlifeAdapter:
    """저축은행·은행 정기예금/적금 수집기."""

    source_id = "finlife"
    source_role = SourceRole.SECONDARY_OFFICIAL
    trust_level = TrustLevel.OFFICIAL_DIRECT

    # sources 행에 쓰이는 값들. 예전에는 collection_service.ensure_source에
    # 하드코딩돼 있어 다른 원천으로 돌리면 잘못된 행이 생겼다.
    source_name = "금융감독원 금융상품통합비교공시 오픈API"
    sector = Sector.SAVINGS_BANK
    mode = CollectionMode.API
    priority = 20
    base_reference = "finlife.fss.or.kr/finlifeapi"
    policy_status = "allowed"
    coverage_status = "partial"

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise CollectorError(
                f"{API_KEY_ENV} 환경변수가 없다. 인증키는 환경변수로만 주입한다 (v3 §16.1)."
            )
        self._api_key = key

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        """권역 × 서비스 조합을 페이지 끝까지 순회한다.

        options:
            services: ("depositProductsSearch", "savingProductsSearch")
            groups:   ("030300",)   권역코드
        """
        services: tuple[str, ...] = tuple(
            request.options.get("services") or ("depositProductsSearch",)
        )
        groups: tuple[str, ...] = tuple(request.options.get("groups") or ("030300",))

        artifacts: list[RawArtifactData] = []
        timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        # httpx는 urllib과 달리 리다이렉트를 기본으로 따라가지 않는다.
        # P0 스크립트(urllib)가 조용히 https로 따라가던 것을 여기서 명시한다.
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for service in services:
                for group in groups:
                    artifacts.extend(await self._fetch_all_pages(client, service, group))
        return artifacts

    async def _fetch_all_pages(
        self, client: httpx.AsyncClient, service: str, group: str
    ) -> list[RawArtifactData]:
        artifacts: list[RawArtifactData] = []
        page_no = 1
        while page_no <= MAX_PAGES:
            payload = await self._get_page(client, service, group, page_no)
            result = payload.get("result") or {}

            artifacts.append(
                RawArtifactData(
                    artifact_type="json",
                    content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    filename=f"{service}_{group}_page{page_no}.json",
                    # 인증키는 저장 전에 지운다 (v3.1 §7.4)
                    request_meta=mask_auth_in_meta(
                        {
                            "url": f"{BASE_URL}/{service}.json",
                            "auth": self._api_key,
                            "service": service,
                            "topFinGrpNo": group,
                            "pageNo": page_no,
                        }
                    ),
                    schema_fingerprint=parser.schema_fingerprint(payload),
                    source_role=self.source_role,
                    trust_level=self.trust_level,
                )
            )

            now_page = int(result.get("now_page_no") or page_no)
            max_page = int(result.get("max_page_no") or page_no)
            if now_page >= max_page:
                break
            page_no += 1
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        return artifacts

    async def _get_page(
        self, client: httpx.AsyncClient, service: str, group: str, page_no: int
    ) -> dict[str, Any]:
        params = {
            "auth": self._api_key,
            "topFinGrpNo": group,
            "pageNo": str(page_no),
        }
        response = await client.get(f"{BASE_URL}/{service}.json", params=params)
        if response.status_code in (403, 429):
            # 차단은 우회하지 않고 즉시 중단한다 (v3 §16.1)
            raise SourceBlockedError(f"차단 응답 {response.status_code}: {service}/{group}")
        response.raise_for_status()

        payload = response.json()
        result = payload.get("result") or {}
        err_cd = result.get("err_cd")
        if err_cd not in (None, "000"):
            raise ParseError(
                f"API 오류 err_cd={err_cd} err_msg={result.get('err_msg')} "
                f"({service}/{group}/page{page_no})"
            )
        return payload

    def parse(self, artifact: RawArtifactData) -> list[ParsedRateRow]:
        """원본 → 표준 행. 경고는 parse_with_warnings로 받는다."""
        rows, _ = self.parse_with_warnings(artifact)
        return rows

    def parse_with_warnings(
        self, artifact: RawArtifactData
    ) -> tuple[list[ParsedRateRow], list[str]]:
        payload = json.loads(artifact.content.decode("utf-8"))
        service = artifact.request_meta["service"]
        group = artifact.request_meta["topFinGrpNo"]
        return parser.parse(payload, service, group)
