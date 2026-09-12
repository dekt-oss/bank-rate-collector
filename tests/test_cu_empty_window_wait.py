"""신협 어댑터의 빈 응답 창 대기 계약.

2026-09-08 04:14 / 09-11 04:11 KST 실행은 136장 전부 `[]`였고, 09-09 03:46 실행은
04:00을 지나면서 뒤쪽 39장이 `[]`로 바뀌었다. 요청 계약은 화면과 같았다(브라우저
실측 동일 파라미터). 어댑터는 이제 1페이지가 비면 카나리(서울 12개월)로 원천
전체가 비어 있는지 가르고, 비어 있으면 상한 안에서 기다렸다가 같은 조회를 다시
한다. 우회가 아니라 대기다.
"""

from __future__ import annotations

import asyncio

import httpx

from rate_monitor.collectors.cu.adapter import (
    CANARY_SIDO,
    CANARY_TERM,
    EMPTY_WINDOW_MAX_WAIT_SECONDS,
    EMPTY_WINDOW_WAIT_SECONDS,
    REQUEST_INTERVAL_SECONDS,
    CuAdapter,
)
from rate_monitor.domain.schemas import CollectionRequest


class FakeUpstream:
    """시각을 sleep으로만 흘리는 가짜 신협 서버.

    `empty_until` 전에는 조건과 무관하게 `[]`를 준다(빈 응답 창). 그 뒤에는
    광주(06)만 실측대로 항상 0건이고 나머지는 1건씩 준다.
    """

    def __init__(self, *, empty_until: float) -> None:
        self.now = 0.0
        self.empty_until = empty_until
        self.calls: list[tuple[str, str, str, str, float]] = []
        self.landings = 0

    async def sleep(self, seconds: float) -> None:
        self.now += seconds

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            self.landings += 1
            return httpx.Response(200, text="<html>landing</html>")
        form = dict(httpx.QueryParams(request.content.decode("utf-8")))
        self.calls.append(
            (request.url.path.rsplit("/", 1)[-1], form["sido"], form["monTy"],
             form["currPage"], self.now)
        )
        if self.now < self.empty_until:
            return httpx.Response(200, json=[])
        if form["sido"] == "06":
            return httpx.Response(200, json=[])
        return httpx.Response(
            200, json=[{"listTotalCount": 1, "cuIngno": f"{form['sido']}-{form['monTy']}"}]
        )


def _fetch(upstream: FakeUpstream, request: CollectionRequest) -> tuple[CuAdapter, list]:
    adapter = CuAdapter(
        sleep=upstream.sleep, transport=httpx.MockTransport(upstream.handler)
    )
    artifacts = asyncio.run(adapter.fetch(request))
    return adapter, artifacts


def _request(*regions: str) -> CollectionRequest:
    return CollectionRequest(
        source_id="cu",
        regions=regions,
        terms=(12,),
        options={"screens": ("findInrst15",)},
    )


def test_empty_window_is_waited_out_and_the_same_query_is_retried() -> None:
    # 두 번 기다리면 창이 끝난다.
    upstream = FakeUpstream(empty_until=EMPTY_WINDOW_WAIT_SECONDS * 2 + 1)

    adapter, artifacts = _fetch(upstream, _request("서울", "부산"))

    assert adapter.empty_window_waits == 2
    assert adapter.empty_window_waited_seconds == EMPTY_WINDOW_WAIT_SECONDS * 2
    assert [a.content for a in artifacts] != [b"[]", b"[]"]
    assert all(a.content != b"[]" for a in artifacts)
    # 서울 12개월이 첫 조회이자 카나리다. 창 안에서는 조회→카나리→대기→재조회.
    canaries = [c for c in upstream.calls if c[1] == CANARY_SIDO and c[2] == str(CANARY_TERM)]
    assert len(canaries) >= 3
    # 기다린 뒤 세션을 새로 받는다.
    assert upstream.landings == 1 + 2
    assert "빈 응답 창 대기 2회 10분" in adapter.fetch_note
    assert "대기 상한" not in adapter.fetch_note
    assert not adapter.fetch_alert


def test_genuine_empty_region_does_not_wait_when_canary_answers() -> None:
    upstream = FakeUpstream(empty_until=0.0)

    adapter, artifacts = _fetch(upstream, _request("광주", "부산"))

    assert adapter.empty_window_waits == 0
    assert adapter.empty_window_waited_seconds == 0
    by_sido = {a.request_meta["sido"]: a.content for a in artifacts}
    assert by_sido["06"] == b"[]"
    assert by_sido["04"] != b"[]"
    # 광주가 비었을 때 카나리 한 번만 더 물었고, 그 답이 있어 기다리지 않았다.
    canaries = [c for c in upstream.calls if c[1] == CANARY_SIDO]
    assert len(canaries) == 1
    assert "빈 응답 창" not in adapter.fetch_note


def test_wait_budget_is_bounded_and_empties_are_then_recorded_for_the_gate() -> None:
    upstream = FakeUpstream(empty_until=float("inf"))

    adapter, artifacts = _fetch(upstream, _request("서울", "부산"))

    expected_waits = int(EMPTY_WINDOW_MAX_WAIT_SECONDS // EMPTY_WINDOW_WAIT_SECONDS)
    assert adapter.empty_window_waits == expected_waits
    assert adapter.empty_window_waited_seconds == EMPTY_WINDOW_MAX_WAIT_SECONDS
    # 상한을 넘으면 그대로 기록한다 — 저장 단계 volume gate가 FAILED로 끝낸다.
    assert [a.content for a in artifacts] == [b"[]", b"[]"]
    assert "대기 상한 60분 초과" in adapter.fetch_note
    # 요청 수는 유한하다: 조회 + 카나리 + 재조회들 + 세션 갱신.
    assert len(upstream.calls) <= 2 * (expected_waits + 1) * 2 + 4
    # 요청 간격은 그대로다 — 대기는 요청을 촘촘히 하지 않는다.
    assert REQUEST_INTERVAL_SECONDS == 1.0
