from rate_monitor.services.reporting_presentation import (
    inject_main_reporting,
    inject_strategy_reporting,
)
from rate_monitor.services.strategy_role_separation_presentation import (
    inject_strategy_role_separation,
)


def test_strategy_role_separation_keeps_data_dom_but_hides_duplicate_explorer() -> None:
    html = """
    <html><head></head><body>
      <section id="planning-zone">
        <article class="sim"><div class="head"></div></article>
      </section>
      <section class="grid primary">
        <article id="map-card"><div id="geo-map"></div></article>
        <article class="top5-card">
          <h2 id="top5-title">경쟁사 TOP 5</h2><p id="top5-copy"></p>
        </article>
      </section>
    </body></html>
    """
    rendered = inject_strategy_role_separation(html)

    assert 'id="strategy-role-separation-style"' in rendered
    assert 'id="strategy-role-separation-script"' in rendered
    assert "#map-card{display:none!important}" in rendered
    assert 'map.setAttribute("aria-hidden","true")' in rendered
    assert "data-strategy-overview-duplicate" not in html
    assert 'kpis.dataset.strategyOverviewDuplicate="true"' in rendered
    assert "현재 판단 가능" in rendered
    assert "내부자료 후 확정 가능" in rendered
    assert "목표 순수신 최소비용 최적금리" in rendered
    assert "지역 상세는 검색 조회에서 확인" in rendered
    assert "가격결정 경쟁 기준 TOP 5" in rendered


def test_main_reporting_is_print_only_and_preserves_csv_json_role() -> None:
    html = (
        '<html><head></head><body><header class="top">'
        '<div class="head-right"></div></header></body></html>'
    )
    rendered = inject_main_reporting(html)

    assert 'id="rate-reporting-style"' in rendered
    assert 'id="main-reporting-script"' in rendered
    assert "보고서 출력" in rendered
    assert "금리 조회·경쟁현황 보고서" in rendered
    assert "CSV/JSON" in rendered
    assert "window.print()" in rendered
    assert "rate-report-printing" in rendered


def test_strategy_reporting_has_calibration_caveat_and_excludes_map_from_report() -> None:
    html = (
        '<html><head></head><body><header class="topbar">'
        '<div class="meta"></div></header></body></html>'
    )
    rendered = inject_strategy_reporting(html)

    assert 'id="strategy-reporting-script"' in rendered
    assert "수신상품 금리결정 검토보고서" in rendered
    assert "내부 수신실적 미보정" in rendered
    assert "최적금리 확정값이 아닙니다" in rendered
    assert "FTP" in rendered
    assert "전국 지도 자체는" in rendered
    assert "중복 포함하지 않습니다" in rendered
    assert "#geo-map" not in rendered.split('id="strategy-reporting-script"', 1)[1]


def test_reporting_injection_is_idempotent() -> None:
    main = (
        '<html><head></head><body><header class="top">'
        '<div class="head-right"></div></header></body></html>'
    )
    once = inject_main_reporting(main)
    assert inject_main_reporting(once) == once

    strategy = (
        '<html><head></head><body><header class="topbar">'
        '<div class="meta"></div></header></body></html>'
    )
    once_strategy = inject_strategy_reporting(strategy)
    assert inject_strategy_reporting(once_strategy) == once_strategy
