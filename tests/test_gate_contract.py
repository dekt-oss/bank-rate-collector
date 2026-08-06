"""게이트가 원천마다 자동으로 분다 (v4 PR 8).

예전에는 `scripts/verify_gate.py`에 원천 이름을 손으로 적었다.

    ("kfcc", "새마을금고"), ("nh_local", "농·축협")

같은 목록이 세 군데 흩어져 있어서, 원천을 하나 더할 때마다 그 파일을 고쳐야
했다. **잊으면 그 원천은 아무 검사도 안 받은 채 발행된다.**

이제 어댑터가 자기 계약을 밝히고 게이트가 그걸 읽는다. 이 파일은 그 구조가
무너지지 않는지 본다.
"""

from pathlib import Path

import pytest

GATE = (Path(__file__).resolve().parents[1] / "scripts" / "verify_gate.py").read_text(
    encoding="utf-8"
)


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    # 어댑터를 세우려면 인증키가 필요하다. 게이트는 클래스만 보므로 값은
    # 아무거나 된다.
    monkeypatch.setenv("FINLIFE_API_KEY", "test")
    monkeypatch.setenv("ECOS_API_KEY", "test")


def _adapters() -> dict:
    from rate_monitor.cli import ADAPTERS

    return ADAPTERS


def test_every_adapter_declares_whether_it_gives_a_max_rate() -> None:
    """이 값이 없으면 게이트가 그 원천의 max_rate 규칙을 검사하지 않는다.

    새마을금고 103,844행과 농·축협 4,920행이 `False`다 — 원천 화면에
    최고우대금리 열이 아예 없다. 그걸 `base_rate`로 메우면 우대금리가 있는
    상품처럼 보인다 (v3 §8.4).
    """
    missing = [
        name for name, cls in _adapters().items()
        if not hasattr(cls, "provides_max_rate")
    ]
    assert missing == [], f"provides_max_rate를 안 밝힌 수집원: {missing}"


def test_the_sources_without_a_max_rate_are_the_ones_we_measured() -> None:
    """실측과 다르면 둘 중 하나가 틀린 것이다."""
    without = {
        name for name, cls in _adapters().items() if not cls.provides_max_rate
    }
    assert without == {"kfcc", "nh_local"}


def test_every_adapter_declares_its_sector() -> None:
    """업권이 섞이면 화면이 둘을 못 가른다."""
    missing = [name for name, cls in _adapters().items() if not getattr(cls, "sector", None)]
    assert missing == []


def test_the_gate_reads_the_adapters_instead_of_a_hand_list() -> None:
    """원천을 더할 때 게이트도 같이 늘어야 한다."""
    assert "from rate_monitor.cli import ADAPTERS" in GATE
    assert "for source_id, adapter_cls in sorted(ADAPTERS.items()):" in GATE
    assert 'getattr(adapter_cls, "provides_max_rate", True)' in GATE


def test_the_gate_skips_a_source_it_has_no_data_for() -> None:
    """0 == 0으로 통과시키면 검사가 아니라 장식이 된다.

    시중은행이 실제로 그랬다 — PR 5를 머지할 때 관측 0건이라 게이트 셋이
    전부 "통과"로 찍혔다. 이제 건너뛴 것을 건너뛰었다고 적는다.
    """
    assert "[건너뜀]" in GATE


def test_the_gate_reports_a_failed_source_without_blocking() -> None:
    """한 원천이 실패해도 나머지는 발행한다. 다만 로그에 남긴다."""
    assert "마지막 수집이 실패한 원천" in GATE
    assert "CONFIRMED_RUN_STATUSES" in GATE


def test_only_fixed_scope_sources_get_a_scope_check() -> None:
    """원천에 따라 갈리는 곳에 기대값을 지어내지 않는다.

    finlife는 권역이 `rate_scope`를 정하므로 고정값이 있다. 새마을금고·신협은
    상품마다 다르므로 안 적었다.
    """
    fixed = {
        name for name, cls in _adapters().items()
        if getattr(cls, "expected_rate_scope", None)
    }
    assert fixed == {"finlife_bank", "finlife_savings_bank"}
