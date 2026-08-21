from pathlib import Path

from rate_monitor.services.strategy_decision_cockpit import inject_strategy_decision_cockpit
from rate_monitor.services.strategy_readability_preference_v2_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_readability_preference_v2,
)


def _render_strategy() -> str:
    template = Path("web/templates/strategy.html").read_text(encoding="utf-8")
    return inject_strategy_decision_cockpit(template)


def test_readability_v2_is_final_strategy_layer_and_scales_real_css() -> None:
    html = _render_strategy()

    assert html.index('id="strategy-ux-refinement-style"') < html.index(STYLE_MARKER)
    assert "body{font-size:17px!important;line-height:1.62!important}" in html
    assert ".head h2{font-size:19px!important}" in html
    assert ".tablewrap td{font-size:12.5px!important}" in html
    pref_table_rule = (
        ".ux-pref-sector .pref-intel-table th,.ux-pref-sector .pref-intel-table td"
        "{font-size:11.5px!important"
    )
    assert pref_table_rule in html
    style_end = html.index("</style>", html.index(STYLE_MARKER))
    assert "zoom:" not in html[html.index(STYLE_MARKER) : style_end]


def test_preference_v2_renders_one_pooled_mutual_finance_card() -> None:
    html = _render_strategy()

    assert "mutual_finance_scopes" in html
    assert 'card("상호금융 통합",mutualScope(selected,intelligence)' in html
    assert "selected.map(k=>labels[k]).join(\"+\")" in html
    assert "전체 우대조건 상품" in html
    assert "상위금리 우대조건 상품" in html
    assert "preference_bearing_share_among_known" in html
    assert "원천별 판별 가능" in html
    assert "미제공(MISSING)은 조건 없음(NONE)" in html


def test_readability_preference_v2_is_idempotent() -> None:
    html = _render_strategy()
    again = inject_strategy_readability_preference_v2(html)

    assert again == html
    assert html.count(STYLE_MARKER) == 1
    assert html.count(SCRIPT_MARKER) == 1
