"""한국은행 ECOS 수신시장 거시지표 어댑터 (Stage E0-3).

기존 ``BokEcosAdapter``는 기준금리 한 가지를 안정적으로 수집한다. 새 월별
거시지표의 계약 변화가 기준금리 run까지 실패시키지 않도록 operational source를
``bok_ecos_macro``로 분리한다. 저장 테이블과 API key는 기존 indicator 경로를
그대로 재사용한다.
"""

from __future__ import annotations

import json
import os
from datetime import date

import httpx

from rate_monitor.collectors.base import CollectorError, SourceBlockedError
from rate_monitor.collectors.bok_ecos import macro_parser
from rate_monitor.domain.enums import CollectionMode, Sector, SourceRole, TrustLevel
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.domain.timeutil import now_kst

BASE_URL = "https://ecos.bok.or.kr/api"
API_KEY_ENV = "ECOS_API_KEY"
REDACTED = "[REDACTED]"
PAGE_SIZE = 100
MONTH_WINDOW = 48
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
BLOCK_STATUSES = (401, 403, 429)


def _month_key_months_ago(today: date, months_ago: int) -> str:
    total = today.year * 12 + today.month - 1 - months_ago
    year, month0 = divmod(total, 12)
    return f"{year:04d}{month0 + 1:02d}"


class BokEcosMacroAdapter:
    """은행 수신 실현금리와 비은행 업권 수신잔액 수집기."""

    source_id = macro_parser.SOURCE_ID
    source_role = SourceRole.PRIMARY_OFFICIAL
    trust_level = TrustLevel.OFFICIAL_DIRECT
    source_name = "한국은행 ECOS 오픈API — 수신시장 거시지표"
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

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        del request  # 원천은 지역/상품 request 옵션을 받지 않는다.
        today = now_kst().date()
        start_month = _month_key_months_ago(today, MONTH_WINDOW - 1)
        end_month = _month_key_months_ago(today, 0)
        timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        artifacts: list[RawArtifactData] = []

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for contract in macro_parser.CONTRACTS:
                path = (
                    f"StatisticSearch/{self._api_key}/json/kr/1/{PAGE_SIZE}"
                    f"/{contract.stat_code}/{macro_parser.CYCLE}"
                    f"/{start_month}/{end_month}/{contract.item_code}"
                )
                url = f"{BASE_URL}/{path}"
                response = await client.get(url)
                if response.status_code in BLOCK_STATUSES:
                    raise SourceBlockedError(
                        f"차단 응답 {response.status_code} — 우회하지 않고 중단한다"
                    )
                response.raise_for_status()
                artifacts.append(
                    RawArtifactData(
                        artifact_type="json",
                        content=response.content,
                        filename=f"{contract.indicator_code}.json",
                        request_meta={
                            "url": self._mask(url),
                            "stat_code": contract.stat_code,
                            "item_code": contract.item_code,
                            "cycle": macro_parser.CYCLE,
                            "from": start_month,
                            "to": end_month,
                            "indicator_code": contract.indicator_code,
                        },
                        schema_fingerprint=(
                            f"{contract.stat_code}/{contract.item_code}/"
                            f"{contract.source_unit}"
                        ),
                        source_role=self.source_role,
                        trust_level=self.trust_level,
                    )
                )
        return artifacts

    def parse_points(
        self, artifact: RawArtifactData
    ) -> tuple[list[macro_parser.IndicatorPoint], list[str]]:
        indicator_code = str(artifact.request_meta.get("indicator_code") or "")
        contract = macro_parser.CONTRACT_BY_INDICATOR.get(indicator_code)
        if contract is None:
            raise CollectorError(f"알 수 없는 ECOS macro indicator: {indicator_code!r}")
        payload = json.loads(artifact.content.decode("utf-8"))
        return macro_parser.parse(payload, contract)
