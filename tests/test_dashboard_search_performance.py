from pathlib import Path

from rate_monitor.services.dashboard_ui_refinement_presentation import (
    inject_dashboard_ui_refinement,
)

SEARCH_TEMPLATE = Path("web/templates/site.html")


def _html() -> str:
    return inject_dashboard_ui_refinement(SEARCH_TEMPLATE.read_text(encoding="utf-8"))


def test_search_keeps_preference_tags_compact_until_filter_use() -> None:
    html = _html()

    assert "search-pref-tags-lazy-v1" in html
    assert 'new Set((look("preference_tags"' not in html
    assert 'prefTags: col.preference_tags == null ? null' in html
    assert ': (look("preference_tags", r[col.preference_tags]) || "")' in html
    assert 'const prefTagValues = (raw) =>' in html
    assert 'const prefTagHas = (raw, code) =>' in html


def test_search_lazy_preference_tag_helpers_cover_all_consumers() -> None:
    html = _html()

    assert 'prefTagValues(r.prefTags)' in html
    assert html.count('prefTagHas(r.prefTags, code)') == 2
    assert html.count('if (!r.prefTags) return false;') == 2
    assert 'if (!r.prefTags || !r.prefTags.size) return false;' not in html
    assert 'r.prefTags.has(code)' not in html
