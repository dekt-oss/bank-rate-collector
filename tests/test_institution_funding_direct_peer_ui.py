from rate_monitor.services.institution_funding_position_presentation import (
    inject_institution_funding_position,
)


def test_strategy_funding_ui_exposes_calibrated_direct_peer_as_separate_layer() -> None:
    html = "<html><head></head><body><section id=\"market-scope\"></section></body></html>"
    rendered = inject_institution_funding_position(html)

    assert "Direct Peer 16 대비" in rendered
    assert "업권 중앙값 대비" in rendered
    assert "sigungu" in rendered
    assert "sido" in rendered
    assert "nationwide" in rendered
    assert "상대비교는 연관성 지표" in rendered
    assert "기관명 미확인" in rendered


def test_strategy_funding_ui_does_not_invent_direct_peer_for_disabled_sector() -> None:
    html = "<html><head></head><body></body></html>"
    rendered = inject_institution_funding_position(html)

    assert "data.direct_peer?.enabled" in rendered
    assert "quality_score" not in rendered
