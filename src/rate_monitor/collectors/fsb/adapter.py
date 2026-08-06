"""저축은행중앙회(FSB) 소비자포털 어댑터.

fetch()만 담당한다. 파싱은 parser가, 저장은 오케스트레이터가 한다
(명세서 v3 §6.2).

## 요청 흐름 (docs/source-recon/fsb.md §3)

    0. 점포 명부   POST /sabfindquic_0100.jct   지부 6개
    1. 화면 GET    /ratedepo_0100.act           세션 쿠키를 받는다
    2. 금리        POST /ratedepo_0100_01.jct   화면 × 기간 × 페이지

데이터는 화면 HTML에 없다. 표는 헤더만 있고 본문은 전부 AJAX로 실린다.
그리고 실제 엔드포인트 확장자는 `.act`가 아니라 **`.jct`**다 — `FSBcomm.js`의
`ajaxSetup.suffix`가 그렇게 정한다.

## `CHK_MONTH`는 결과를 걸러내지 않는다

정찰 문서 §4는 기간이 요청 차원이라고 적었지만 실물은 다르다. 한 행에 그
상품이 취급하는 모든 기간이 함께 오고, 36개월만 취급하는 상품도 12개월
조회에 나온다 (`collectors/fsb/parser.py` 모듈 설명의 fixture 근거).

그래서 기간마다 요청을 나누지 않는다. 화면당 한 번이면 6개 기간이 다 온다.
요청량이 화면 2 × 기간 6 = 12에서 화면 2로 줄고, 같은 비교단위를 여섯 번
저장해 `동일 실행 내 관측 중복` 게이트를 깨뜨리는 일도 없어진다.

## 지역

`AREA`는 지점 금리를 주는 차원이 **아니다.** `YN_Busan`은 "부산에서 가입
가능한 저축은행"을 고르는 필터이고, 금리는 그대로 본점 기준이다. 기본값은
지역 필터 없이 전국을 받는 것이다 — 지역으로 좁힐 이유가 없다.

차단 우회는 하지 않는다 (v3 §0.2, §16.1).
"""

import asyncio
import json
from typing import Any

import httpx

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.fsb import parser
from rate_monitor.domain.enums import CollectionMode, Sector, SourceRole, TrustLevel
from rate_monitor.domain.schemas import CollectionRequest, ParsedRateRow, RawArtifactData
from rate_monitor.domain.timeutil import now_kst

BASE_URL = "https://www.fsb.or.kr"

# 우리를 밝히는 User-Agent. 브라우저인 척하지 않는다 (v3 §7.3.8).
USER_AGENT = "rate-monitor/1 (+public rate disclosure collector; 1 req/s)"

REQUEST_INTERVAL_SECONDS = 1.0
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 20.0

# 화면 → (GET할 화면 경로, POST할 데이터 엔드포인트).
# 입출금자유예금(`ratanym`)은 뺐다. 정찰에서 `ANYM_REC` 없이 헤더만 돌아왔고
# 원인을 찾지 못했다 (docs/source-recon/fsb.md §5). 빈 결과를 성공으로
# 저장하면 "취급 상품 없음"과 구분되지 않는다.
SCREENS = {
    "ratedepo": ("/ratedepo_0100.act", "/ratedepo_0100_01.jct"),
    "rateinst": ("/rateinst_0100.act", "/rateinst_0100_01.jct"),
}

# 화면의 라디오 버튼 값 (docs/source-recon/fsb.md §3.5).
# 요청에 하나를 실어야 해서 12를 쓴다. 결과를 거르지 않으므로 어느 값을
# 넣든 6개 기간이 다 온다.
ALL_TERMS = (1, 3, 6, 12, 24, 36)
REQUEST_TERM = 12

# 가입방법 전체. 하나로 좁히면 그 채널로만 파는 상품이 통째로 빠진다.
ALL_JOIN_LOCATIONS = "1|2|3|4|5|9"

# 저축은행 찾기의 지부 코드. 시도가 아니라 중앙회 지부다 (§4-2).
BRANCH_AREAS = ("01", "02", "03", "04", "05", "06")
BRANCH_PAGE_SIZE = 500

PAGE_SIZE = 100
MAX_PAGES = 40  # 실측 최대 397건. 한 화면이 4,000건을 넘으면 구조가 바뀐 것이다.
MAX_REQUESTS = 120

BLOCK_MARKERS = ("Request Blocked", "Access Denied", "접속이 차단")
BLOCK_STATUSES = (400, 403, 429)


class FsbAdapter:
    """저축은행 정기예금·정기적금 수집기 (1차 원천)."""

    source_id = "fsb"
    # 명세서 v3 §7.2가 FSB를 저축은행 1차 원천으로 둔다. finlife는 교차검증.
    source_role = SourceRole.PRIMARY_OFFICIAL
    trust_level = TrustLevel.OFFICIAL_DIRECT

    source_name = "저축은행중앙회 소비자포털"
    sector = Sector.SAVINGS_BANK
    mode = CollectionMode.HTTP
    priority = 10
    base_reference = "fsb.or.kr"
    # 사이트 이용약관 자체가 없어 수집 허용 범위를 확인할 수 없었다
    # (docs/source-recon/fsb.md §5.1). allowed로 올리지 않는다.
    policy_status = "unknown"
    coverage_status = "partial"

    def __init__(self) -> None:
        # 점포 명부. 금리 화면에 소재지가 없어 별도 화면에서 받아 여기 둔다.
        #
        # request_meta에 실어 나르지 않는다. 27KB짜리 값이 화면 2 × 기간 6 =
        # 12개 아티팩트에 복제되면 스냅샷이 300KB 넘게 불어난다. 대신 명부
        # 응답 자체를 아티팩트로 저장하므로 나중에 다시 파싱해도 복원된다 —
        # `parse_with_warnings`가 명부 아티팩트를 만나면 여기를 채운다.
        self._directory: dict[str, list[dict[str, Any]]] = {}

    # ── 요청 ────────────────────────────────────────────────────────────

    async def _post(
        self, client: httpx.AsyncClient, path: str, body: dict[str, Any]
    ) -> tuple[bytes, dict[str, Any]]:
        response = await client.post(f"{BASE_URL}{path}", json=body)
        raw = response.content
        if response.status_code in BLOCK_STATUSES:
            text = raw.decode("utf-8", "ignore")
            if any(marker in text for marker in BLOCK_MARKERS):
                raise SourceBlockedError(
                    f"차단 응답 {response.status_code}: {path} — 우회하지 않고 중단한다"
                )
        response.raise_for_status()
        return raw, json.loads(raw.decode("utf-8", "replace"))

    def _rate_body(self, *, query_date: str, area: str, term: int,
                   start: int, end: int) -> dict[str, str]:
        """정기예금·정기적금 요청 본문 (docs/source-recon/fsb.md §3.4).

        `TB_SEQ1~3`·`SEARCH_CODE`는 의미를 모른다. 빈 값으로 두면 동작하므로
        알아내기 전까지 채우지 않는다.
        """
        year, month, day = query_date.split("-")
        return {
            "REG_DATE": query_date,
            "CHG_DATE": query_date,
            "AREA": area,
            "SELECT_YEAR": year,
            "SELECT_MONTH": month,
            "SELECT_DAY": day,
            "TB_SEQ1": "", "TB_SEQ2": "", "TB_SEQ3": "", "ORDERBY": "",
            "JOIN_LOCATION": ALL_JOIN_LOCATIONS,
            "CHK_MONTH": str(term),
            "END_NUM": str(end),
            "START_NUM": str(start),
            "SEARCH_CODE": "", "SEARCH_SELECT_IN": "", "SEARCH_TEXT_IN": "",
        }

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        query_date = (request.as_of or _today()).isoformat()
        screens = tuple(request.options.get("screens") or SCREENS)
        # 요청은 특정 기간으로 나가지만 응답은 전 기간을 준다. 여기 값은
        # 무엇을 받을지가 아니라 무엇으로 물어볼지를 정할 뿐이다.
        area = str(request.options.get("area") or "")
        only_terms = tuple(request.terms) if request.terms else None

        artifacts: list[RawArtifactData] = []
        seen_bodies: set[bytes] = set()
        requests_made = 0

        timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        ) as client:
            # 0단계: 점포 명부. 금리 화면에 소재지가 없어 여기서 가져온다.
            branch_payloads: list[tuple[str, bytes]] = []
            for code in BRANCH_AREAS:
                raw, _ = await self._post(
                    client,
                    "/sabfindquic_0100.jct",
                    {
                        "AREA": code, "IBANK": "", "MBANK": "", "PLOAN": "",
                        "N_FUNDS": "", "CD": "", "CDP": "", "ATM": "",
                        "END_NUM": str(BRANCH_PAGE_SIZE), "START_NUM": "1",
                        "STR_SORT": "SEQ DESC", "ADDR": "",
                        "SEARCHTEXT": "", "SEARCHVAL": "",
                    },
                )
                requests_made += 1
                branch_payloads.append((code, raw))
                await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

            for code, raw in branch_payloads:
                if raw in seen_bodies:
                    continue
                seen_bodies.add(raw)
                artifacts.append(
                    self._artifact(
                        raw,
                        filename=f"branches_{code}.json",
                        meta={"kind": "branches", "area": code},
                        fingerprint="branches",
                    )
                )

            # 명부는 지부별 응답을 합쳐 한 벌로 만든다. 금리 행이 은행 이름으로
            # 찾아 쓰므로 지부 경계를 넘어 하나여야 한다.
            for _, raw in branch_payloads:
                self._merge_branches(json.loads(raw.decode("utf-8", "replace")))

            # 1단계: 화면을 GET해 세션 쿠키를 받는다.
            for screen in screens:
                screen_path, data_path = SCREENS[screen]
                await client.get(f"{BASE_URL}{screen_path}")
                requests_made += 1
                await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

                # 2단계: 페이지 끝까지. 기간은 나누지 않는다.
                start = 1
                for page in range(MAX_PAGES):
                    if requests_made >= MAX_REQUESTS:
                        raise SourceBlockedError(
                            f"요청 상한 {MAX_REQUESTS}회에 도달했다. 설정을 확인한다"
                        )
                    end = start + PAGE_SIZE - 1
                    raw, payload = await self._post(
                        client,
                        data_path,
                        self._rate_body(
                            query_date=query_date, area=area,
                            term=REQUEST_TERM, start=start, end=end,
                        ),
                    )
                    requests_made += 1
                    await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

                    rows = payload.get("REC") or []
                    if raw not in seen_bodies:
                        seen_bodies.add(raw)
                        artifacts.append(
                            self._artifact(
                                raw,
                                filename=f"{screen}_p{page + 1}.json",
                                meta={
                                    "kind": "rate",
                                    "screen": screen,
                                    "area": area,
                                    "page_offset": start - 1,
                                    "only_terms": list(only_terms or ()),
                                },
                                fingerprint=parser.schema_fingerprint(payload),
                            )
                        )

                    total = parser.total_count(payload)
                    if not rows or total is None or end >= total:
                        break
                    start = end + 1
        return artifacts

    def _artifact(
        self, body: bytes, *, filename: str, meta: dict, fingerprint: str
    ) -> RawArtifactData:
        return RawArtifactData(
            artifact_type="json",
            content=body,
            filename=filename,
            # 인증키가 없는 원천이라 마스킹할 값이 없다. 쿠키·토큰은 넣지 않는다.
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
        payload = json.loads(artifact.content.decode("utf-8", "replace"))
        meta: dict[str, Any] = artifact.request_meta

        if meta.get("kind") == "branches":
            # 점포 명부는 금리 행을 만들지 않는다. 대신 명부를 채운다.
            # 저장된 아티팩트만으로 다시 파싱해도 주소가 붙는 경로다.
            found = self._merge_branches(payload)
            return [], ([] if found else ["점포 명부가 비어 있다"])

        rows, warnings = parser.parse(
            payload,
            screen=str(meta["screen"]),
            area=str(meta.get("area") or ""),
            branches=self._directory,
            page_offset=int(meta.get("page_offset") or 0),
            only_terms=tuple(meta.get("only_terms") or ()) or None,
        )
        if rows and not self._directory:
            # 명부를 먼저 읽지 않으면 79개 기관의 본점 주소가 통째로 빠진다.
            # 행은 그대로 만들어지므로 조용히 지나가기 쉬운 실패다.
            warnings.append(
                "점포 명부가 비어 있어 본점 주소를 붙이지 못했다."
                " 명부 아티팩트를 먼저 파싱해야 한다"
            )
        return rows, warnings

    def _merge_branches(self, payload: dict[str, Any]) -> int:
        """지부별 명부 응답을 하나로 합친다. 합친 뒤 은행 수를 돌려준다."""
        for bank, entries in parser.parse_branches(payload).items():
            existing = self._directory.setdefault(bank, [])
            keys = {e["source_outlet_key"] for e in existing}
            existing.extend(e for e in entries if e["source_outlet_key"] not in keys)
        return len(self._directory)


def _today():
    """오늘, **한국 날짜로**.

    저축은행중앙회에 "오늘 기준 공시"를 물어보는 값이다. UTC 날짜를 쓰면
    정기 수집(22:00 UTC)이 도는 시점에 한국은 이미 다음 날 07:00이라
    하루 전 날짜로 물어보게 된다.
    """
    return now_kst().date()
