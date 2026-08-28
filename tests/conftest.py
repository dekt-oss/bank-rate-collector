"""테스트에서 실시간 health handler의 현재시각을 결정적으로 고정한다."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def deterministic_live_health_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """과거 GitHub run fixture가 벽시계 날짜에 따라 깨지지 않게 한다.

    production은 ``RATE_MONITOR_HEALTH_NOW``를 설정하지 않으므로 실제 현재시각을
    그대로 사용한다. Pytest가 실행한 Node subprocess만 이 값을 상속한다.
    """
    monkeypatch.setenv("RATE_MONITOR_HEALTH_NOW", "2026-08-10T22:20:00Z")
