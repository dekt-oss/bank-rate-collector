from rate_monitor.services.rate_funding_matrix_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_rate_funding_matrix,
)


def test_matrix_presentation_is_fail_closed_and_future_ready() -> None:
    html = '<html><head></head><body><div id="institution-funding-position"></div></body></html>'
    rendered = inject_rate_funding_matrix(html)

    assert STYLE_MARKER in rendered
    assert SCRIPT_MARKER in rendered
    assert "Rate × Funding Matrix" in rendered
    assert "시점정합 금리 이력이 부족" in rendered
    assert "현재 공시금리가 존재하더라도 과거 수신잔액에 소급해 붙이지 않습니다" in rendered
    assert "12M 대표 기본금리" in rendered
    assert "6M 수신증가율" in rendered
    assert "동월 exact pair 중앙값" in rendered
    assert "인과효과 판정이 아닙니다" in rendered
    assert inject_rate_funding_matrix(rendered) == rendered
