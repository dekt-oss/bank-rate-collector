"""Search 초기 로딩 시 per-row 우대조건 Set 할당을 제거한다.

`preference_tags`는 공백 구분 canonical 코드 문자열이다. 기존 화면은 모든 금리행을
펼칠 때마다 이를 `Set`으로 변환해 수십만 개의 Set/배열을 영구 할당했다. 필터 의미는
그대로 유지하면서 행에는 원문 문자열을 보관하고, 실제 우대조건 UI/필터가 필요할 때만
짧은 코드를 해석한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

MARKER = "search-pref-tags-lazy-v1"


def _replace_required(html: str, old: str, new: str, label: str, *, count: int = 1) -> str:
    if old not in html:
        raise DashboardBuildError(f"Search 성능 보정 anchor를 찾지 못했다: {label}")
    return html.replace(old, new, count)


def inject_dashboard_search_performance(html: str) -> str:
    """Search row expansion의 preference tag allocation을 lazy string 방식으로 바꾼다."""
    if MARKER in html or 'id="conditions"' not in html:
        return html

    rendered = html
    old_tags = '''      prefTags: col.preference_tags == null ? null
        : new Set((look("preference_tags", r[col.preference_tags]) || "")
            .split(" ").filter(Boolean)),'''
    new_tags = '''      prefTags: col.preference_tags == null ? null
        : (look("preference_tags", r[col.preference_tags]) || ""),'''
    rendered = _replace_required(rendered, old_tags, new_tags, "row preference tags")

    helper_anchor = '''  fetch(data.table_url || "data/table.json")'''
    helpers = '''  // search-pref-tags-lazy-v1: per-row Set 할당 없이 필요할 때만 해석한다.
  const prefTagValues = (raw) => raw ? String(raw).split(" ").filter(Boolean) : [];
  const prefTagHas = (raw, code) => raw ? (` ${raw} `).includes(` ${code} `) : false;

  fetch(data.table_url || "data/table.json")'''
    rendered = _replace_required(rendered, helper_anchor, helpers, "preference tag helpers")

    rendered = _replace_required(
        rendered,
        'r.prefTags ? [...r.prefTags] : []',
        'prefTagValues(r.prefTags)',
        "preference tag code census",
        count=1,
    )
    old_counts = (
        'r.prefTags.forEach((code) => counts.set(code, '
        '(counts.get(code) || 0) + 1));'
    )
    new_counts = (
        'prefTagValues(r.prefTags).forEach((code) => counts.set(code, '
        '(counts.get(code) || 0) + 1));'
    )
    rendered = _replace_required(
        rendered,
        old_counts,
        new_counts,
        "preference tag counts",
        count=1,
    )
    rendered = _replace_required(
        rendered,
        'if (!r.prefTags || !r.prefTags.size) return false;',
        'if (!r.prefTags) return false;',
        "preference tag empty guard",
        count=2,
    )
    rendered = _replace_required(
        rendered,
        'if (r.prefTags.has(code)) hit = true;',
        'if (prefTagHas(r.prefTags, code)) hit = true;',
        "preference tag match",
        count=2,
    )
    return rendered
