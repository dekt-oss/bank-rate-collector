"""Stage A 베이크 이후 source template 단일 진실원 계약."""

from pathlib import Path

from rate_monitor.services.site_service import DEFAULT_STRATEGY_TEMPLATE


def test_baked_strategy_template_remains_direct_source_of_truth() -> None:
    html = DEFAULT_STRATEGY_TEMPLATE.read_text(encoding="utf-8")

    assert "수신상품 전략 대시보드" in html
    assert "function aggregateProducts" in html
    assert 'viewBox="130 -5 450 675" role="img"' in html
    assert not Path("src/rate_monitor/services/strategy_refinement_service.py").exists()
