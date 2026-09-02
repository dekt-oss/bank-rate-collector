from pathlib import Path

from rate_monitor.services.dashboard_search_performance_presentation import (
    inject_dashboard_search_performance,
)
from rate_monitor.services.strategy_unfinished_collapse_presentation import (
    inject_strategy_unfinished_collapse,
)


def test_search_boot_prefers_existing_gzip_and_keeps_plain_fallback() -> None:
    html = Path("web/templates/site.html").read_text(encoding="utf-8")

    rendered = inject_dashboard_search_performance(html)

    assert "search-pref-tags-lazy-v2" in rendered
    assert 'const tableGzipUrl = `${tableUrl}.gz`;' in rendered
    assert "fetch(tableGzipUrl)" in rendered
    assert 'new DecompressionStream("gzip")' in rendered
    assert "fetch(tableUrl)" in rendered
    assert 'return loadPlainTable();' in rendered
    assert 'loadTable()\n    .then((table) => {' in rendered
    assert 'loadTable()\n    .then((res) => {' not in rendered


def test_search_boot_does_not_scan_every_row_to_build_preference_code_census() -> None:
    html = Path("web/templates/site.html").read_text(encoding="utf-8")

    rendered = inject_dashboard_search_performance(html)
    old_pref_census = '''PREF_TAG_CODES = [...new Set(ALL.flatMap((r) =>
        r.prefTags ? [...r.prefTags] : []))];'''

    assert "const prefTagLookup = ((table.lookups || {}).preference_tags || []);" in rendered
    assert "PREF_TAG_CODES = [...new Set(prefTagLookup.flatMap(prefTagValues))];" in rendered
    assert old_pref_census not in rendered
    assert "new Set((look(\"preference_tags\"" not in rendered


def test_search_performance_injection_is_idempotent() -> None:
    html = Path("web/templates/site.html").read_text(encoding="utf-8")
    once = inject_dashboard_search_performance(html)

    assert inject_dashboard_search_performance(once) == once


def test_strategy_unfinished_sections_get_progressive_disclosure_runtime() -> None:
    html = Path("web/templates/strategy.html").read_text(encoding="utf-8")

    rendered = inject_strategy_unfinished_collapse(html)

    assert 'id="strategy-unfinished-collapse-style"' in rendered
    assert 'id="strategy-unfinished-collapse-script"' in rendered
    assert ".rate-funding-matrix-blocked,.axistext" in rendered
    assert "기간별 이력 데이터가 없습니다" in rendered
    assert 'POPULATED_SELECTOR="tbody tr,.change,.pref,.busan-rate-item' in rendered
    assert 'card.dataset.collapsed="true"' in rendered
    assert 'button.querySelector("span").textContent="펼치기"' in rendered
    assert 'button.querySelector("span").textContent=collapsed?"접기":"펼치기"' in rendered
    assert 'button.setAttribute("aria-expanded",String(collapsed))' in rendered


def test_strategy_unfinished_collapse_is_strategy_only_and_idempotent() -> None:
    strategy = Path("web/templates/strategy.html").read_text(encoding="utf-8")
    search = Path("web/templates/site.html").read_text(encoding="utf-8")
    once = inject_strategy_unfinished_collapse(strategy)

    assert inject_strategy_unfinished_collapse(once) == once
    assert inject_strategy_unfinished_collapse(search) == search
