# ruff: noqa: E501
# Evidence branch only: this comment triggers the existing Search A/B workflow.
"""Search 초기 로딩의 전송량과 per-row 우대조건 파싱 비용을 줄인다.

`preference_tags`는 공백 구분 canonical 코드 문자열이다. 필터 의미는 유지하면서
행에는 원문 문자열을 보관하고 실제 우대조건 UI/필터가 필요할 때만 해석한다.
이미 생성되는 gzip companion을 브라우저가 지원할 때 우선 사용하되, 압축 해제나
요청이 실패하면 기존 JSON으로 fail-open 한다. 둘 다 동일 산출물의 표현만 다르다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

MARKER = "search-pref-tags-lazy-v2"


def _replace_required(html: str, old: str, new: str, label: str, *, count: int = 1) -> str:
    if old not in html:
        raise DashboardBuildError(f"Search 성능 보정 anchor를 찾지 못했다: {label}")
    return html.replace(old, new, count)


def inject_dashboard_search_performance(html: str) -> str:
    """Search row expansion과 초기 table fetch 비용을 줄인다."""
    if MARKER in html or 'id="conditions"' not in html:
        return html

    rendered = html
    old_tags = '''      prefTags: col.preference_tags == null ? null
        : new Set((look("preference_tags", r[col.preference_tags]) || "")
            .split(" ").filter(Boolean)),'''
    new_tags = '''      prefTags: col.preference_tags == null ? null
        : (look("preference_tags", r[col.preference_tags]) || ""),'''
    rendered = _replace_required(rendered, old_tags, new_tags, "row preference tags")

    loader_anchor = '''  fetch(data.table_url || "data/table.json")
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })'''
    loader = '''  // search-pref-tags-lazy-v2: 행마다 Set을 만들지 않고 lookup에서 코드 목록을 만든다.
  const prefTagValues = (raw) => raw ? String(raw).split(" ").filter(Boolean) : [];
  const prefTagHas = (raw, code) => raw ? (` ${raw} `).includes(` ${code} `) : false;
  const tableUrl = data.table_url || "data/table.json";
  const tableGzipUrl = `${tableUrl}.gz`;
  const loadPlainTable = async () => {
    const res = await fetch(tableUrl);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };
  const loadTable = async () => {
    if (!("DecompressionStream" in window)) return loadPlainTable();
    try {
      const res = await fetch(tableGzipUrl);
      if (!res.ok) throw new Error(`gzip HTTP ${res.status}`);
      const encoded = (res.headers.get("content-encoding") || "").toLowerCase();
      if (encoded.includes("gzip")) return res.json();
      if (!res.body) throw new Error("gzip response body missing");
      const stream = res.body.pipeThrough(new DecompressionStream("gzip"));
      return new Response(stream).json();
    } catch (error) {
      console.warn("압축 금리표 로딩 실패, 일반 JSON으로 재시도합니다.", error);
      return loadPlainTable();
    }
  };

  loadTable()'''
    rendered = _replace_required(
        rendered,
        loader_anchor,
        loader,
        "compressed table loader",
    )

    rendered = _replace_required(
        rendered,
        '''      PREF_TAG_CODES = [...new Set(ALL.flatMap((r) =>
        r.prefTags ? [...r.prefTags] : []))];''',
        '''      const prefTagLookup = ((table.lookups || {}).preference_tags || []);
      PREF_TAG_CODES = [...new Set(prefTagLookup.flatMap(prefTagValues))];''',
        "preference tag code census",
    )
    rendered = _replace_required(
        rendered,
        'r.prefTags ? [...r.prefTags] : []',
        'prefTagValues(r.prefTags)',
        "preference tag code rendering",
    )
    rendered = _replace_required(
        rendered,
        'r.prefTags.forEach((code) => counts.set(code, '
        '(counts.get(code) || 0) + 1));',
        'prefTagValues(r.prefTags).forEach((code) => counts.set(code, '
        '(counts.get(code) || 0) + 1));',
        "preference tag counts",
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
