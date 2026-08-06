"""한국은행 ECOS 어댑터 (v4 §7).

fetch()만 담당한다. 파싱은 parser가, 저장은 `indicator_service`가 한다.

계약은 정찰로 확정했다 (`docs/source-recon/bok-ecos.md`).

    GET https://ecos.bok.or.kr/api/StatisticSearch/{키}/json/kr/1/{N}
        /722Y001/D/{시작}/{끝}/0101000

**인증키가 경로에 들어간다.** 쿼리스트링이 아니라 URL 자체에 박히므로
저장할 때 반드시 지운다 (v3 §16.1) — finlife의 `auth=` 마스킹과 같은 이유다.
"""

import json
import os
from datetime import date, timedelta

import httpx

from rate_monitor.collectors.base import CollectorError, SourceBlockedError
from rate_monitor.collectors.bok_ecos import parser
from rate_monitor.domain.enums import CollectionMode, Sector, SourceRole, TrustLevel
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.domain.timeutil import now_kst

BASE_URL = "https://ecos.bok.or.kr/api"
API_KEY_ENV = "ECOS_API_KEY"
REDACTED = "[REDACTED]"

# 얼마나 거슬러 받는가.
#
# 기준금리는 몇 달씩 안 바뀐다. 최근 한 건만 받으면 그 값이 언제부터인지
# 모르고, 우리가 며칠 못 돌린 사이의 변경도 놓친다. 넉넉히 받아 두고
# 저장 쪽이 중복을 거른다 (UNIQUE 제약).
LOOKBACK_DAYS = 400
PAGE_SIZE = 700

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0

BLOCK_STATUSES = (401, 403, 429)


class BokEcosAdapter:
    """한국은행 기준금리 수집기."""

    source_id = parser.SOURCE_ID
    source_role = SourceRole.PRIMARY_OFFICIAL
    trust_level = TrustLevel.OFFICIAL_DIRECT

    source_name = "한국은행 ECOS 오픈API"
    # 금융상품이 아니라 지표다. 업권으로 분류하지 않는다 (v4 §7.1).
    sector = Sector.BANK
    mode = CollectionMode.API
    priority = 30
    base_reference = "ecos.bok.or.kr/api/StatisticSearch"
    policy_status = "allowed"
    coverage_status = "partial"

    def __init__(self, api_key: str | None = None) -> None:
        # **앞뒤 공백을 지운다.** 인증키가 경로에 들어가는 API라 개행 하나가
        # `%0A`로 인코딩되어 붙고, ECOS는 그걸 다른 키로 읽어 INFO-100
        # (인증키가 유효하지 않습니다)을 준다.
        #
        # 2026-08-06에 실제로 갈렸다. 같은 시크릿으로 정찰(run 31098447877)은
        # 성공했고 수집(run 31101956888)은 INFO-100으로 실패했다. 두 코드의
        # 인증키 처리 차이가 `.strip()` 하나였다 — 정찰 스크립트는 지웠고
        # 어댑터는 안 지웠다.
        key = (api_key or os.environ.get(API_KEY_ENV) or "").strip()
        if not key:
            raise CollectorError(
                f"{API_KEY_ENV} 환경변수가 없다. 인증키는 환경변수로만 주입한다 (v3 §16.1)."
            )
        self._api_key = key

    def _mask(self, text: str) -> str:
        return text.replace(self._api_key, REDACTED)

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        today = now_kst().date()
        start: date = today - timedelta(days=LOOKBACK_DAYS)
        stamp = "%Y%m%d"
        path = (
            f"StatisticSearch/{self._api_key}/json/kr/1/{PAGE_SIZE}"
            f"/{parser.STAT_CODE}/{parser.CYCLE}"
            f"/{start.strftime(stamp)}/{today.strftime(stamp)}/{parser.ITEM_CODE}"
        )
        url = f"{BASE_URL}/{path}"

        timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code in BLOCK_STATUSES:
                raise SourceBlockedError(
                    f"차단 응답 {response.status_code} — 우회하지 않고 중단한다"
                )
            response.raise_for_status()
            body = response.content

        return [
            RawArtifactData(
                artifact_type="json",
                content=body,
                filename="bok_base_rate.json",
                # **인증키가 경로에 있으므로 주소를 그대로 남기지 않는다.**
                request_meta={
                    "url": self._mask(url),
                    "stat_code": parser.STAT_CODE,
                    "item_code": parser.ITEM_CODE,
                    "cycle": parser.CYCLE,
                    "from": start.isoformat(),
                    "to": today.isoformat(),
                },
                schema_fingerprint=parser.STAT_CODE + "/" + parser.ITEM_CODE,
                source_role=self.source_role,
                trust_level=self.trust_level,
            )
        ]

    def parse_points(
        self, artifact: RawArtifactData
    ) -> tuple[list[parser.IndicatorPoint], list[str]]:
        payload = json.loads(artifact.content.decode("utf-8"))
        return parser.parse(payload, cycle=artifact.request_meta.get("cycle", parser.CYCLE))
