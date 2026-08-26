"""Strategy 상품군 후속 runtime을 본체 IIFE lexical scope 안으로 재배치한다."""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

FOLLOWUP_SCRIPT_ID = "dashboard-strategy-product-followup-script"
INSIGHT_SCRIPT_ID = "dashboard-strategy-savings-insight-script"
READABILITY_SCRIPT_ID = "dashboard-strategy-scope-readability-script"
CLARITY_SCRIPT_ID = "dashboard-strategy-decision-clarity-script"
FOLLOWUP_RUNTIME_MARKER = "dashboard-strategy-product-followup-runtime"
INSIGHT_RUNTIME_MARKER = "dashboard-strategy-savings-insight-runtime"
READABILITY_RUNTIME_MARKER = "dashboard-strategy-scope-readability-runtime"
CLARITY_RUNTIME_MARKER = "dashboard-strategy-decision-clarity-runtime"


def _extract_standalone_iife(html: str, script_id: str) -> tuple[str, str]:
    marker = f'<script id="{script_id}">'
    start = html.find(marker)
    if start < 0:
        raise DashboardBuildError(f"Strategy 상품군 standalone runtime을 찾지 못했다: {script_id}")
    source_start = start + len(marker)
    end = html.find("</script>", source_start)
    if end < 0:
        raise DashboardBuildError(
            f"Strategy 상품군 standalone runtime 종료를 찾지 못했다: {script_id}"
        )
    source = html[source_start:end].strip()
    prefix = "(()=>{"
    suffix = "})();"
    if not source.startswith(prefix) or not source.endswith(suffix):
        raise DashboardBuildError(f"Strategy 상품군 runtime IIFE 계약이 예상과 다르다: {script_id}")
    body = source[len(prefix) : -len(suffix)].strip("\n")
    rendered = html[:start] + html[end + len("</script>") :]
    return rendered, body


def _inject_blocks_into_strategy_iife(html: str, blocks: list[tuple[str, str]]) -> str:
    data_marker = '<script id="rate-monitor-data" type="application/json">'
    data_start = html.find(data_marker)
    if data_start < 0:
        raise DashboardBuildError("Strategy 상품군 runtime repair의 데이터 anchor를 찾지 못했다")
    data_end = html.find("</script>", data_start + len(data_marker))
    if data_end < 0:
        raise DashboardBuildError("Strategy 상품군 runtime repair의 데이터 종료를 찾지 못했다")
    script_tag = html.find("<script>", data_end + len("</script>"))
    if script_tag < 0:
        raise DashboardBuildError("Strategy 상품군 runtime repair의 본체 script를 찾지 못했다")
    script_start = script_tag + len("<script>")
    script_end = html.find("</script>", script_start)
    if script_end < 0:
        raise DashboardBuildError("Strategy 상품군 runtime repair의 본체 script 종료를 찾지 못했다")
    iife_close = html.rfind("})();", script_start, script_end)
    if iife_close < 0:
        raise DashboardBuildError("Strategy 상품군 runtime repair의 본체 IIFE 종료를 찾지 못했다")
    runtime = "\n".join(
        f"/* {marker} */\n{{\n{body}\n}}" for marker, body in blocks
    )
    return html[:iife_close] + runtime + "\n" + html[iife_close:]


def repair_strategy_product_scope_runtime(html: str) -> str:
    """별도 script로 만들어진 Strategy 후속 코드를 본체 IIFE 내부 block으로 옮긴다."""
    readability_expected = f'<script id="{READABILITY_SCRIPT_ID}">' in html
    clarity_expected = f'<script id="{CLARITY_SCRIPT_ID}">' in html
    if (
        FOLLOWUP_RUNTIME_MARKER in html
        and INSIGHT_RUNTIME_MARKER in html
        and (READABILITY_RUNTIME_MARKER in html or not readability_expected)
        and (CLARITY_RUNTIME_MARKER in html or not clarity_expected)
    ):
        return html
    if 'data-product-mode="deposit"' not in html:
        return html

    rendered, followup = _extract_standalone_iife(html, FOLLOWUP_SCRIPT_ID)
    rendered, insight = _extract_standalone_iife(rendered, INSIGHT_SCRIPT_ID)
    blocks = [
        (FOLLOWUP_RUNTIME_MARKER, followup),
        (INSIGHT_RUNTIME_MARKER, insight),
    ]
    if f'<script id="{READABILITY_SCRIPT_ID}">' in rendered:
        rendered, readability = _extract_standalone_iife(rendered, READABILITY_SCRIPT_ID)
        blocks.append((READABILITY_RUNTIME_MARKER, readability))
    if f'<script id="{CLARITY_SCRIPT_ID}">' in rendered:
        rendered, clarity = _extract_standalone_iife(rendered, CLARITY_SCRIPT_ID)
        blocks.append((CLARITY_RUNTIME_MARKER, clarity))
    return _inject_blocks_into_strategy_iife(rendered, blocks)
