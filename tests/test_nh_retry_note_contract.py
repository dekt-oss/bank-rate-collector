"""NH fetch note는 RepeatGuard 요약과 retry telemetry를 함께 보존한다."""

import asyncio
from collections import Counter

from rate_monitor.collectors.nh_local import parser
from rate_monitor.collectors.nh_local.adapter import LIST_SCREEN, NhLocalAdapter
from rate_monitor.domain.schemas import CollectionRequest


async def _no_sleep(_delay: float) -> None:
    return None


def test_fetch_note_keeps_guard_summary_when_retry_note_is_appended(monkeypatch) -> None:
    """Retry note 추가가 RepeatGuard summary를 덮어쓰지 않는지 실제 fetch 경로로 본다."""
    adapter = NhLocalAdapter(sleep=_no_sleep)
    outlet = parser.NhOutlet(brc="817020", name="가락농협", address="부산광역시 강서구")

    monkeypatch.setattr(adapter, "_load_prefixes", lambda _request: None)
    monkeypatch.setattr(parser, "parse_outlet_list", lambda _html: [outlet])
    monkeypatch.setattr(parser, "outlets_in", lambda rows, _prefixes: rows)
    monkeypatch.setattr(parser, "schema_fingerprint", lambda _html: "schema")

    async def fake_get(_client, screen, _params, *, phase):
        if screen == LIST_SCREEN:
            # 실제 _get이 한 번 transient retry 뒤 성공한 상태를 재현한다.
            adapter._retry_count = 1
            adapter._retry_reasons = Counter({"NETWORK_CONNECT": 1})
            return b"outlet-list"
        return f"detail:{screen}:{phase}".encode()

    monkeypatch.setattr(adapter, "_get", fake_get)

    artifacts = asyncio.run(adapter.fetch(CollectionRequest(source_id="nh_local")))

    assert len(artifacts) == 3  # 명부 1 + 기본 상품 화면 2
    assert "응답 3장" in adapter.fetch_note
    assert "재시도 1회 (NETWORK_CONNECT 1)" in adapter.fetch_note
