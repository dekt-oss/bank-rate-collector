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
from rate_monitor.domain.enums import (
    CollectionMode,
    RateScope,
    Sector,
    SourceRole,
    TrustLevel,
)
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


def _page_number(value: object) -> int | None:
    """응답의 쪽 번호. 못 읽으면 None이다.

    `or` 대체값을 쓰지 않는다 — 0이나 빈 문자열을 "현재 쪽"으로 바꾸면
    모르는 것이 완료가 된다.

    >>> _page_number(3), _page_number("3")
    (3, 3)
    >>> _page_number(None), _page_number(""), _page_number("x"), _page_number(0)
    (None, None, None, None)
    """
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class FinlifeAdapter:
    """finlife 오픈API 수집기. **권역마다 따로 세운다** (v4 §6.2).

    같은 API가 저축은행(`030300`)과 시중은행(`020000`)을 함께 준다. 예전에는
    하나의 `source_id="finlife"`가 둘을 다 받았는데, 그러면 화면이 둘을 못
    가른다 — 시중은행은 참고지표로 내려가고 저축은행은 메인 비교표에 남아야
    한다 (v4 §0.7).

    그래서 권역 하나에 어댑터 하나다. 아래 두 하위 클래스를 쓴다.
    """

    source_id = "finlife_savings_bank"
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
    # optionList의 intr_rate2가 최고금리다. 없는 행은 NULL로 남는다.
    provides_max_rate = True

    # 이 어댑터가 받는 권역. 하나만 둔다 — 하나의 실행이 하나의 소스에
    # 대응해야 `collection_runs.source_id`가 그 실행의 행들과 맞는다.
    groups: tuple[str, ...] = ("030300",)

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise CollectorError(
                f"{API_KEY_ENV} 환경변수가 없다. 인증키는 환경변수로만 주입한다 (v3 §16.1)."
            )
        self._api_key = key
        # fetch에서 생긴 경고를 담아 둔다. 저장 계층은 parse 단계의 경고만
        # 받아 가므로, 여기 모아 뒀다가 첫 아티팩트를 파싱할 때 얹는다.
        self._warnings: list[str] = []

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        """권역 × 서비스 조합을 페이지 끝까지 순회한다.

        options:
            services: ("depositProductsSearch", "savingProductsSearch")
            groups:   ("030300",)   권역코드
        """
        services: tuple[str, ...] = tuple(
            request.options.get("services") or ("depositProductsSearch",)
        )
        # 요청이 권역을 덮어쓸 수 있지만, 이 어댑터가 맡은 것과 다르면
        # 거부한다. 저축은행 어댑터로 은행을 받으면 실행 이력의 source_id와
        # 저장된 행의 source_id가 어긋난다 (v4 §6.5 "레코드 혼합 0").
        groups: tuple[str, ...] = tuple(request.options.get("groups") or self.groups)
        wrong = [g for g in groups if parser.GROUP_SOURCE_ID.get(g) != self.source_id]
        if wrong:
            raise CollectorError(
                f"{self.source_id}가 맡지 않은 권역: {wrong}. "
                f"이 어댑터는 {list(self.groups)}만 받는다"
            )

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

            # 쪽수를 못 읽으면 **끝난 것으로 치지 않는다.**
            #
            # 예전에는 `int(result.get("max_page_no") or page_no)`였다. 값이
            # 없거나 0이면 현재 쪽이 되어 그 자리에서 멈춘다 — 모르는 것을
            # 완료로 바꾸는 기본값이다. 2026-08-06 run 31069995734에서
            # 양쪽 서비스가 1쪽에서 멈춰 4,010행이 1,075행이 됐고, 상태는
            # success였다.
            #
            # 이제는 못 읽으면 경고를 남기고 멈춘다. 멈추는 것은 같지만
            # 조용하지 않다 — 물량 게이트(scripts/volume_gate.py)가 뒤에서
            # 한 번 더 잡는다.
            now_page = _page_number(result.get("now_page_no"))
            max_page = _page_number(result.get("max_page_no"))
            if max_page is None or now_page is None:
                self._warnings.append(
                    f"쪽수를 읽지 못해 {page_no}쪽에서 멈춘다 "
                    f"({service}/{group}: now={result.get('now_page_no')!r}, "
                    f"max={result.get('max_page_no')!r})"
                )
                break
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
        rows, warnings = parser.parse(payload, service, group)
        if self._warnings:
            # fetch 단계의 경고를 여기서 흘려보낸다. 한 번만 나가도록 비운다.
            warnings = [*self._warnings, *warnings]
            self._warnings = []
        return rows, warnings


class FinlifeSavingsBankAdapter(FinlifeAdapter):
    """저축은행 (`030300`). 예전 `finlife`가 받던 것과 같은 데이터다.

    본점 기준 공시라 지역별 지점금리가 아니다 (v3.1 §6.4). 저축은행중앙회
    수집분과 같은 상품을 다시 싣기 때문에 화면 메인에는 FSB 쪽만 내고 이쪽은
    교차검증용으로 둔다 (v4 §11.1, `config/presentation.yaml`).
    """

    source_id = "finlife_savings_bank"
    source_name = "금융감독원 비교공시 — 저축은행"
    sector = Sector.SAVINGS_BANK
    groups = ("030300",)
    expected_rate_scope = RateScope.HEAD_OFFICE_REFERENCE


class FinlifeBankAdapter(FinlifeAdapter):
    """시중은행 (`020000`). 메인 비교표가 아니라 참고지표다 (v4 §6.4).

    전국 공시라 부산 구·군에 연결하지 않는다. finlife의 `companySearch`가
    주는 지역정보는 시도별 점포 존재 여부이지 상품별 지역금리가 아니다
    (v4 §6.3).
    """

    source_id = "finlife_bank"
    source_name = "금융감독원 비교공시 — 시중은행"
    sector = Sector.BANK
    groups = ("020000",)
    expected_rate_scope = RateScope.NATIONWIDE
