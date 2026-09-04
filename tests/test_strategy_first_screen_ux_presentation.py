"""Strategy 첫 화면 정보 위계/중앙값 presentation 회귀 테스트."""

from pathlib import Path

from rate_monitor.services.strategy_first_screen_ux_presentation import (
    SCRIPT,
    STYLE,
    inject_strategy_first_screen_ux,
)


def _fixture() -> str:
    return """<!doctype html>
<html><head></head><body>
<section id="market-scope"></section>
<section class="grid kpis">
  <article class="card kpi green"><div id="market-max"></div></article>
  <article class="card kpi gold">
    <div class="klabel">시장 평균 금리 <span class="basis-label">12개월</span></div>
    <div id="mean"></div>
    <div class="kfoot">
      <span>상품 대표 최고금리 평균</span><span id="trend-delta"></span>
    </div>
  </article>
  <article class="card kpi teal">
    <div id="count"></div><span id="median">중앙값 —</span>
  </article>
  <article class="card kpi threshold"><div id="top10"></div></article>
</section>
</body></html>"""


def test_injects_first_screen_refinement_once() -> None:
    rendered = inject_strategy_first_screen_ux(_fixture())
    assert rendered.count('id="strategy-first-screen-ux-style"') == 1
    assert rendered.count('id="strategy-first-screen-ux-script"') == 1
    assert inject_strategy_first_screen_ux(rendered) == rendered


def test_partial_strategy_composition_without_kpis_is_ignored() -> None:
    fragment = '<html><head></head><body><div id="market-scope"></div></body></html>'
    assert inject_strategy_first_screen_ux(fragment) == fragment


def test_strategy_sector_parent_selection_is_compact_and_soft() -> None:
    assert "min-height:32px!important" in STYLE
    assert "width:13px!important" in STYLE
    assert "background:#fff3f8!important" in STYLE
    assert "background:var(--accent-strong)" not in STYLE
    assert "box-shadow:none!important" in STYLE


def test_scope_contract_is_reduced_to_inline_helper_copy() -> None:
    assert "display:flex!important" in STYLE
    assert "border:0!important" in STYLE
    assert "background:transparent!important" in STYLE
    assert 'setScopeLabel(labels[0],"비교 기준")' in SCRIPT
    assert 'setScopeLabel(labels[1],"이력")' in SCRIPT
    assert 'setScopeLabel(labels[2],"예측")' in SCRIPT


def test_first_screen_kpi_order_and_median_contract_are_explicit() -> None:
    assert "[compareCard,medianCard,maxCard,topCard]" in SCRIPT
    assert '"시장 중앙값"' in SCRIPT
    assert '"상품 대표 최고금리 중앙값"' in SCRIPT
    assert 'const medianSource=$("median")' in SCRIPT
    assert 'replace(/^중앙값\\s*/,"")' in SCRIPT
    assert ".kpis #median{display:none!important}" in STYLE


def test_change_is_display_only_and_history_mean_contract_stays_intact() -> None:
    template = Path("web/templates/strategy.html").read_text(encoding="utf-8")
    # 원본 집계는 mean과 median을 모두 계속 계산한다. 첫 화면만 presentation에서
    # median을 mirror하므로 기간별 이력/시뮬레이터의 mean 계약은 건드리지 않는다.
    assert "mean:mean(rates),median:median(rates)" in template
    assert "mean_max_rate" in template
    assert '$("plan-market-mean")' in template
