"""Stage E0 예금시장 외부지표 ECOS 어댑터.

기존 기준금리 ``bok_ecos``와 source_id를 분리한다. 월별 시장 지표 한 종류가
실패해도 기준금리 수집 계약과 실행 이력을 건드리지 않기 위해서다.

6개 계열 모두 2026-08-18 ECOS metadata + live StatisticSearch Evidence Gate를
통과한 코드만 사용한다. raw artifact는 계열별로 하나씩 남긴다.
"""

from __future__ import annotations

import json
import os
from datetime import date

import httpx

from rate_monitor.collectors.base import CollectorError, SourceBlockedError
from rate_monitor.collectors.bok_ecos import deposit_market_parser as parser
from rate_monitor.domain.enums import CollectionMode, Sector, SourceRole, TrustLevel
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.domain.timeutil import now_kst

BASE_URL = "https://ecos.bok.or.kr/api"
API_KEY_ENV = "ECOS_API_KEY"
REDACTED = "[REDACTED]"
LOOKBACK_YEARS = 4
PAGE_SIZE = 700
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
BLOCK_STATUSES = (401, 403, 429)


class BokEcosDepositMarketAdapter:
    """예금시장 pricing/funding regime용 한국은행 월별 지표 수집기."""

    source_id = parser.SOURCE_ID
    source_role = SourceRole.PRIMARY_OFFICIAL
    trust_level = TrustLevel.OFFICIAL_DIRECT
    source_name = "한국은행 ECOS 예금시장 월별지표"
    # 금융상품이 아니라 참고지표다. 기존 ECOS 기준금리와 같은 방식으로
    # 비교표 universe에 섞이지 않는다.
    sector = Sector.BANK
    mode = CollectionMode.API
    priority = 31
    base_reference = "ecos.bok.or.kr/api/StatisticSearch"
    policy_status = "allowed"
    coverage_status = "partial"

    def __init__(self, api_key: str | None = None) -> None:
        key = (api_key or os.environ.get(API_KEY_ENV) or "").strip()
        if not key:
            raise CollectorError(
                f"{API_KEY_ENV} 환경변수가 없다. 인증키는 환경변수로만 주입한다."
            )
        self._api_key = key

    def _mask(self, text: str) -> str:
        return text.replace(self._api_key, REDACTED)

    @staticmethod
    def _window(today: date) -> tuple[str, str]:
        start = date(today.year - LOOKBACK_YEARS, today.month, 1)
        return start.strftime("%Y%m"), today.strftime("%Y%m")

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        del request  # source 자체가 검증된 6개 계열의 고정 universe다.
        today = now_kst().date()
        start, end = self._window(today)
        timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        artifacts: list[RawArtifactData] = []

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for spec in parser.SERIES:
                path = (
                    f"StatisticSearch/{self._api_key}/json/kr/1/{PAGE_SIZE}"
                    f"/{spec.stat_code}/{parser.CYCLE}/{start}/{end}/{spec.item_code}"
                )
                url = f"{BASE_URL}/{path}"
                response = await client.get(url)
                if response.status_code in BLOCK_STATUSES:
                    raise SourceBlockedError(
                        f"{spec.indicator_code}: 차단 응답 {response.status_code} — 우회하지 않는다"
                    )
                response.raise_for_status()
                artifacts.append(
                    RawArtifactData(
                        artifact_type="json",
                        content=response.content,
                        filename=f"{spec.indicator_code}.json",
                        request_meta={
                            "url": self._mask(url),
                            "indicator_code": spec.indicator_code,
                            "stat_code": spec.stat_code,
                            "item_code": spec.item_code,
                            "cycle": parser.CYCLE,
                            "from": start,
                            "to": end,
                            "source_unit": spec.source_unit,
                            "storage_unit": spec.unit,
                        },
                        schema_fingerprint=f"{spec.stat_code}/{spec.item_code}/{parser.CYCLE}",
                        source_role=self.source_role,
                        trust_level=self.trust_level,
                    )
                )
        return artifacts

    def parse_points(
        self, artifact: RawArtifactData
    ) -> tuple[list[parser.IndicatorPoint], list[str]]:
        payload = json.loads(artifact.content.decode("utf-8"))
        indicator_code = str(artifact.request_meta.get("indicator_code") or "")
        return parser.parse(payload, indicator_code=indicator_code)
