"""신협(CU) 전자공시 금리비교 어댑터.

fetch()만 담당한다. 파싱은 parser가, 저장은 오케스트레이터가 한다
(명세서 v3 §6.2).

## 요청 흐름 (docs/source-recon/cu.md)

    1. 화면 GET   /cu/ad/inrstCmpr/findInrst15CmprList.do?mi=201001   세션 쿠키
    2. 지역 목록  POST /cu/ad/inrstCmpr/findInrstSido.do
    3. 금리       POST /cu/ad/inrstCmpr/findInrst15CmprListResult.do

화면 HTML에 금리 행이 없다. 표는 헤더만 있고 본문은 AJAX로 실린다.
응답은 JSON 배열이고 `listTotalCount`가 각 행에 들어 있다.

## "전체"는 빈 문자열이 아니라 `AA`다

화면 JS(`fn_move_query_condition`)가 아무것도 선택하지 않으면 `AA`를 넣는다.
빈 문자열로 보내면 조용히 0건이 돌아온다 — 오류가 아니라 빈 결과라서
"취급 상품 없음"과 구분되지 않는다. 실제로 정찰에서 여기 걸렸다.

`highLimtAmt`도 마찬가지로 화면 기본값 `"10,000,000"`(쉼표 포함)이 필요하다.

## 기간은 진짜 요청 차원이다

FSB와 달리 여기서는 `monTy`가 결과를 실제로 거른다. 응답 행의 `monTy`는
요청값과 항상 같다. 그래서 기간마다 요청을 나눈다.

차단 우회는 하지 않는다 (v3 §0.2, §16.1).
"""

import asyncio
import json
from typing import Any

import httpx

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.cu import parser
from rate_monitor.domain.enums import CollectionMode, Sector, SourceRole, TrustLevel
from rate_monitor.domain.schemas import CollectionRequest, ParsedRateRow, RawArtifactData

BASE_URL = "https://www.cu.co.kr"
PATH_PREFIX = "/cu/ad/inrstCmpr"

USER_AGENT = "rate-monitor/1 (+public rate disclosure collector; 1 req/s)"
REQUEST_INTERVAL_SECONDS = 1.0
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 20.0

# 화면 → 화면 진입 메뉴번호. 상품유형 대응은 parser.SCREEN_PRODUCT_TYPE에 있다.
SCREENS = {"findInrst15": "201001", "findInrst17": "201002"}

# 화면의 지역 체크박스 값. 이름은 화면이 주지 않으므로 조회 조건 표시용으로만
# 쓰고, 행정구역 공식 코드로 취급하지 않는다 (명세서 v3.1 §11).
#
# ── 이 표는 추측이 아니라 실측이다 (2026-08-05) ─────────────────────
#
# 처음에는 하위지역 **개수**만 보고 코드를 시도에 대응시켰다가 18개 중
# 7개를 틀렸다. 경북 데이터가 "충북"으로, 전남이 "경남"으로 나가고 있었다.
# 개수는 여러 시도가 우연히 같을 수 있어 근거가 되지 못한다.
#
# 그래서 `findInrstSido.do`가 주는 **하위지역 이름**으로 다시 맞췄다. 각
# 코드마다 그 시도에만 있는 지명을 근거로 적는다.
#
#   01 강남·관악·노원      서울        02 가평·과천·남양주    경기
#   03 강화·미추홀·옹진    인천        04 기장·부산진·사상    부산
#   05 달서·달성·수성      대구        06 광산               광주
#   07 대덕·유성          대전        09 울주               울산
#   10 강릉·속초·양양      강원        11 경산·경주·구미      경북
#   12 거제·김해·밀양      경남        13 괴산·단양·증평      충북
#   14 계룡·공주·당진      충남        15 고창·군산·김제      전북
#   16 강진·고흥·목포      전남        17 서귀포·제주        제주
#
# **08은 존재하지 않고 세종도 없다.** 18은 광주(광산·남구…)와 전남(강진·
# 고흥…)이 한 코드에 섞여 있어 시도 하나로 부를 수 없다. 새마을금고에서
# 본 것과 같은 형태다 — 화면의 지역 구분은 행정구역과 일대일이 아니다.
SIDO_NAMES = {
    "01": "서울", "02": "경기", "03": "인천", "04": "부산", "05": "대구",
    "06": "광주", "07": "대전", "09": "울산", "10": "강원", "11": "경북",
    "12": "경남", "13": "충북", "14": "충남", "15": "전북", "16": "전남",
    "17": "제주",
    # 광주와 전남이 섞인 묶음이다. 어느 한쪽 이름을 붙이면 거짓이 된다.
    "18": "광주·전남",
}

# 화면 기본값. 빈 값으로 바꾸면 0건이 돌아온다.
ALL = "AA"
ALL_CHANNELS = "A"
DEFAULT_LIMIT_AMOUNT = "10,000,000"
DEFAULT_TERMS = (6, 12, 24, 36)

PAGE_SIZE = 50
MAX_PAGES = 200
MAX_REQUESTS = 2000

BLOCK_MARKERS = ("Request Blocked", "Access Denied", "접속이 차단")
BLOCK_STATUSES = (400, 403, 429)


class CuAdapter:
    """신협 거치식·적립식 예탁금 수집기."""

    source_id = "cu"
    source_role = SourceRole.PRIMARY_OFFICIAL
    trust_level = TrustLevel.OFFICIAL_DIRECT

    source_name = "신협 전자공시 금리비교"
    sector = Sector.CU
    mode = CollectionMode.HTTP
    priority = 10
    base_reference = "cu.co.kr/cu/ad/inrstCmpr"
    # 이용약관상 수집 허용 범위를 확인하지 못했다. allowed로 올리지 않는다.
    policy_status = "review"
    # 지역과 최고 우대금리를 동시에 주는 유일한 원천이다.
    provides_max_rate = True
    coverage_status = "partial"

    # ── 요청 ────────────────────────────────────────────────────────────

    async def _post(
        self, client: httpx.AsyncClient, path: str, body: dict[str, Any]
    ) -> tuple[bytes, Any]:
        response = await client.post(f"{BASE_URL}{path}", data=body)
        raw = response.content
        if response.status_code in BLOCK_STATUSES:
            text = raw.decode("utf-8", "ignore")
            if any(marker in text for marker in BLOCK_MARKERS):
                raise SourceBlockedError(
                    f"차단 응답 {response.status_code}: {path} — 우회하지 않고 중단한다"
                )
        response.raise_for_status()
        return raw, json.loads(raw.decode("utf-8", "replace"))

    def _rate_body(self, *, page: int, sido: str, term: int) -> dict[str, str]:
        """금리 조회 본문 (docs/source-recon/cu.md §3).

        `AA`와 `"10,000,000"`은 화면 기본값이다. 빈 값으로 바꾸면 0건이 온다.
        """
        return {
            "currPage": str(page),
            "listMaxCnt": str(PAGE_SIZE),
            "highLimtAmt": DEFAULT_LIMIT_AMOUNT,
            "monTy": str(term),
            "sido": sido,
            "subSido": ALL,
            "tretChlTy": ALL_CHANNELS,
            "sortColumn": "CU_NM",
            "sortAsc": "A",
            "searchTxt": "",
        }

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        screens = tuple(request.options.get("screens") or SCREENS)
        terms = tuple(request.terms or request.options.get("terms") or DEFAULT_TERMS)
        sidos = self._resolve_sidos(request)

        artifacts: list[RawArtifactData] = []
        seen_bodies: set[bytes] = set()
        requests_made = 0

        timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            for screen in screens:
                # 화면을 먼저 GET해 세션 쿠키를 받는다.
                await client.get(
                    f"{BASE_URL}{PATH_PREFIX}/{screen}CmprList.do",
                    params={"mi": SCREENS[screen]},
                )
                requests_made += 1
                await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

                for sido in sidos:
                    for term in terms:
                        page = 1
                        while page <= MAX_PAGES:
                            if requests_made >= MAX_REQUESTS:
                                raise SourceBlockedError(
                                    f"요청 상한 {MAX_REQUESTS}회에 도달했다."
                                    " 설정을 확인한다"
                                )
                            raw, rows = await self._post(
                                client,
                                f"{PATH_PREFIX}/{screen}CmprListResult.do",
                                self._rate_body(page=page, sido=sido, term=term),
                            )
                            requests_made += 1
                            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

                            if raw not in seen_bodies:
                                seen_bodies.add(raw)
                                artifacts.append(
                                    self._artifact(
                                        raw,
                                        filename=(
                                            f"{screen}_{sido}_{term}m_p{page}.json"
                                        ),
                                        meta={
                                            "screen": screen,
                                            "sido": sido,
                                            "sido_name": SIDO_NAMES.get(sido),
                                            "term_months": term,
                                            "page_offset": (page - 1) * PAGE_SIZE,
                                        },
                                        fingerprint=parser.schema_fingerprint(rows),
                                    )
                                )

                            total = parser.total_count(rows)
                            if not rows or total is None or page * PAGE_SIZE >= total:
                                break
                            page += 1
        return artifacts

    def _resolve_sidos(self, request: CollectionRequest) -> list[str]:
        """수집할 지역 코드.

        `regions`에 이름을 주면 코드로 옮긴다. 아무것도 없으면 `AA`(전체)
        한 번으로 끝낸다 — 지역별로 나눠 돌 이유가 없다.
        """
        if not request.regions:
            return [ALL]
        by_name = {name: code for code, name in SIDO_NAMES.items()}
        wanted: list[str] = []
        unknown: list[str] = []
        for region in request.regions:
            code = by_name.get(region)
            if code is None:
                unknown.append(region)
            elif code not in wanted:
                wanted.append(code)
        if unknown:
            raise ValueError(f"신협 화면에 없는 지역: {unknown}")
        return wanted

    def _artifact(
        self, body: bytes, *, filename: str, meta: dict, fingerprint: str
    ) -> RawArtifactData:
        return RawArtifactData(
            artifact_type="json",
            content=body,
            filename=filename,
            # 인증키가 없는 원천이라 마스킹할 값이 없다. 쿠키는 넣지 않는다.
            request_meta=meta,
            schema_fingerprint=fingerprint,
            source_role=self.source_role,
            trust_level=self.trust_level,
        )

    # ── 파싱 ────────────────────────────────────────────────────────────

    def parse(self, artifact: RawArtifactData) -> list[ParsedRateRow]:
        rows, _ = self.parse_with_warnings(artifact)
        return rows

    def parse_with_warnings(
        self, artifact: RawArtifactData
    ) -> tuple[list[ParsedRateRow], list[str]]:
        rows = json.loads(artifact.content.decode("utf-8", "replace"))
        meta: dict[str, Any] = artifact.request_meta
        return parser.parse(
            rows,
            screen=str(meta["screen"]),
            sido=str(meta.get("sido") or ""),
            sido_name=meta.get("sido_name"),
            page_offset=int(meta.get("page_offset") or 0),
        )
