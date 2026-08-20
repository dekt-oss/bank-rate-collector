from rate_monitor.services.main_map_presentation import MAIN_MAP_SCRIPT, MAIN_MAP_STYLE
from rate_monitor.services.strategy_ux_refinement_presentation import _CSS, _JS


def test_main_dashboard_owns_region_map_and_report_output() -> None:
    assert "main-map-shell" in MAIN_MAP_STYLE
    assert "보고서 출력" in MAIN_MAP_SCRIPT
    assert "전국 예·적금 금리 비교 보고서" in MAIN_MAP_SCRIPT
    assert "@page { size:A4 landscape" in MAIN_MAP_STYLE
    assert "금리결정 시나리오와 전략 판단은 전략 대시보드 보고서" in MAIN_MAP_SCRIPT


def test_strategy_removes_duplicate_map_but_keeps_decision_scope() -> None:
    assert ".workspace-detail.primary:not(.busan-focus) .mapcard{display:none!important}" in _CSS
    assert "지역·지도 상세는 검색 조회로 통합했습니다." in _JS
    assert "경쟁상단·금리결정 근거만 남깁니다." in _JS
    assert "지역 상세 보기" in _JS


def test_strategy_exposes_decision_readiness_boundary() -> None:
    assert "금리결정 준비도" in _JS
    assert "시장 위치 · 경쟁상단" in _JS
    assert "시장·외부환경 시나리오" in _JS
    assert "최종 최적금리 자동추천" in _JS
    assert "수신증분·재예치·중도해지·FTP 실적 calibration 전에는 보류" in _JS
    assert "목표 순수신을 최소비용으로 달성하는 최적금리" in _JS


def test_strategy_report_is_print_pdf_ready() -> None:
    assert "보고서 출력" in _JS
    assert "수신상품 전략 의사결정 보고서" in _JS
    assert "@page{size:A4 portrait" in _CSS
    assert "내부 실적 calibration 전에는 최종 최적금리 자동추천" in _JS
