from pathlib import Path

from rate_monitor.services.site_service import _add_strategy_nav

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_TEMPLATE = ROOT / "web" / "templates" / "strategy.html"


def test_main_header_uses_same_two_page_navigation_as_strategy() -> None:
    main_fixture = """
    <html><head></head><body>
      <header class="top">
        <div class="brand">검색 화면</div>
        <div class="head-right"></div>
      </header>
    </body></html>
    """
    main_html = _add_strategy_nav(main_fixture)
    strategy_html = STRATEGY_TEMPLATE.read_text(encoding="utf-8")

    for html in (main_html, strategy_html):
        assert 'aria-label="주요 화면"' in html
        assert html.index("검색 조회") < html.index("전략 대시보드")
        assert 'href="./"' in html
        assert 'href="strategy.html"' in html

    assert (
        '<a href="./" class="active" aria-current="page">검색 조회</a>'
        in main_html
    )
    assert '<a href="strategy.html">전략 대시보드</a>' in main_html
    assert (
        '<a href="./">검색 조회</a><a href="strategy.html" class="active" '
        'aria-current="page">전략 대시보드</a>'
        in strategy_html
    )


def test_main_navigation_matches_strategy_visual_contract() -> None:
    main_html = _add_strategy_nav(
        '<html><head></head><body><header class="top">'
        '<div class="head-right"></div></header></body></html>'
    )

    assert 'id="main-page-nav-style"' in main_html
    assert "padding: 4px; border-radius: 11px" in main_html
    assert "background: rgba(255,255,255,.10)" in main_html
    assert "padding: 7px 15px" in main_html
    assert "font-size: 12px; font-weight: 760" in main_html
    assert "color: var(--accent-ink); background: #fff" in main_html
    assert "box-shadow: 0 2px 8px rgba(48,26,53,.16)" in main_html


def test_main_navigation_keeps_strategy_release_gate_boundary() -> None:
    main_fixture = (
        '<html><head></head><body><header class="top">'
        '<div class="head-right"></div></header></body></html>'
    )

    assert "전략 대시보드" not in main_fixture
    assert "전략 대시보드" in _add_strategy_nav(main_fixture)
