#!/usr/bin/env python3
"""Patch generated preview HTML with D0-verified market-funding UI.

The canonical site builder is intentionally untouched. This script runs only in
the isolated Strategy preview workflow, so removing the preview branch or this
step restores the pre-v2 screens byte-for-byte from the normal build path.

The existing Strategy macro panel remains in the DOM because it is still part
of the canonical production presentation. Preview-only CSS hides it visually,
while the new compact Strategy strip links back to the full Search market view.
That makes the role split reviewable without changing production behavior.
"""

from __future__ import annotations

from pathlib import Path

from rate_monitor.services.market_funding_preview_presentation import (
    SEARCH_MARKER,
    STRATEGY_MARKER,
    inject_search_market_funding_preview,
    inject_strategy_market_funding_preview,
    load_preview_snapshot,
)

ROLE_SPLIT_STYLE = """
<style id="market-funding-preview-role-split">
  /* Preview only: the full macro panel moves to Search/current-status. */
  #external-market-context { display: none !important; }
</style>
""".strip()


def main() -> None:
    out = Path("site-public")
    index_path = out / "index.html"
    strategy_path = out / "strategy.html"
    if not index_path.is_file() or not strategy_path.is_file():
        raise SystemExit("preview site must be built before market-funding patch")

    snapshot = load_preview_snapshot()
    index_html = index_path.read_text(encoding="utf-8")
    strategy_html = strategy_path.read_text(encoding="utf-8")
    patched_index = inject_search_market_funding_preview(index_html, snapshot)
    patched_strategy = inject_strategy_market_funding_preview(strategy_html, snapshot)
    if 'id="market-funding-preview-role-split"' not in patched_strategy:
        patched_strategy = patched_strategy.replace(
            "</head>", ROLE_SPLIT_STYLE + "\n</head>", 1
        )

    if SEARCH_MARKER not in patched_index:
        raise SystemExit("Search market-funding preview marker missing after patch")
    if STRATEGY_MARKER not in patched_strategy:
        raise SystemExit("Strategy market-funding preview marker missing after patch")
    if STRATEGY_MARKER in patched_index or SEARCH_MARKER in patched_strategy:
        raise SystemExit("market-funding preview IA leaked across surfaces")
    if "#external-market-context { display: none !important; }" not in patched_strategy:
        raise SystemExit("legacy Strategy macro panel is not hidden in preview")

    index_path.write_text(patched_index, encoding="utf-8")
    strategy_path.write_text(patched_strategy, encoding="utf-8")
    print(
        "market-funding preview patched: "
        f"search={len(patched_index):,}B strategy={len(patched_strategy):,}B "
        f"analysis={snapshot['analysis_month']} leading={snapshot['leading_rate_month']}"
    )


if __name__ == "__main__":
    main()
