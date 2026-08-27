"""Preview-only market-funding presentation for Search and Strategy.

This module deliberately consumes a small, verified D0 snapshot instead of the
production DB. It exists so the information architecture can be reviewed before
we introduce the S0/S1 persistence contract. Canonical publication is unchanged
unless ``RATE_MONITOR_MARKET_FUNDING_PREVIEW=1`` is explicitly set.

The full macro view belongs on Search/current-status. Strategy gets only a
compact context strip, avoiding duplicate charts and keeping that page focused
on competitor pricing, own position, funding response, and product design.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

PREVIEW_ENV = "RATE_MONITOR_MARKET_FUNDING_PREVIEW"
DEFAULT_SNAPSHOT = Path("config/market-funding-preview-snapshot.json")
SEARCH_MARKER = 'id="market-funding-preview"'
STRATEGY_MARKER = 'id="strategy-market-funding-preview"'
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

_SECTORS = (
    (
        "bank",
        "예금은행",
        "bank_total_deposit_balance_eom",
        "bank_term_deposit_1y_rate",
    ),
    (
        "savings_bank",
        "저축은행",
        "savings_bank_deposit_balance_eom",
        "savings_bank_term_deposit_1y_rate",
    ),
    (
        "credit_union",
        "신협",
        "credit_union_deposit_balance_eom",
        "credit_union_term_deposit_1y_rate",
    ),
    (
        "kfcc",
        "새마을금고",
        "kfcc_deposit_balance_eom",
        "kfcc_term_deposit_1y_rate",
    ),
)

_SEARCH_STYLE = """
<style id="market-funding-preview-style">
  .mf-preview{margin:16px 0 14px;padding:18px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,#fff,#faf7fa);box-shadow:0 12px 28px rgba(74,43,73,.08)}
  .mf-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:13px}.mf-head h2{margin:0;font-size:17px;letter-spacing:-.025em}.mf-head p{margin:4px 0 0;color:var(--ink-2);font-size:11.5px}.mf-badges{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.mf-badge{padding:4px 7px;border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--ink-2);font:700 10px var(--mono)}.mf-badge.lead{border-color:#e9c6d6;background:var(--accent-bg);color:var(--accent-ink)}
  .mf-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}.mf-card{min-width:0;padding:12px;border:1px solid var(--line-soft);border-radius:12px;background:#fff}.mf-card .sector{display:flex;align-items:center;justify-content:space-between;gap:8px;color:var(--ink-2);font-size:11px;font-weight:750}.mf-card .balance{display:block;margin-top:6px;color:var(--ink);font:800 20px/1.1 var(--mono);letter-spacing:-.035em}.mf-card .delta{font:750 10px var(--mono)}.mf-card .delta.up{color:var(--crit)}.mf-card .delta.down{color:var(--ok)}.mf-card .rates{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:9px;padding-top:8px;border-top:1px solid var(--line-soft)}.mf-card .rates span{display:block;color:var(--ink-3);font-size:9.5px}.mf-card .rates b{display:block;margin-top:2px;color:var(--ink-2);font:750 11px var(--mono)}.mf-card .rates b.lead{color:var(--accent-ink)}
  .mf-main{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(300px,.7fr);gap:10px}.mf-panel{padding:13px;border:1px solid var(--line-soft);border-radius:12px;background:#fff}.mf-panel-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}.mf-panel-head b{font-size:12px}.mf-panel-head span{color:var(--ink-3);font-size:9.5px}.mf-chart{width:100%;height:188px;display:block}.mf-gridline{stroke:#eee7ef;stroke-width:1}.mf-line{fill:none;stroke-width:2.2;vector-effect:non-scaling-stroke}.mf-line.bank{stroke:#5b2f64}.mf-line.savings_bank{stroke:#d33a7c}.mf-line.credit_union{stroke:#8d6e8f}.mf-line.kfcc{stroke:#6f8b7d}.mf-axis{fill:#887c8b;font:9px var(--mono)}.mf-legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:4px;color:var(--ink-2);font-size:9.5px}.mf-legend i{display:inline-block;width:15px;height:2px;margin-right:4px;vertical-align:middle;background:currentColor}.mf-legend .bank{color:#5b2f64}.mf-legend .savings_bank{color:#d33a7c}.mf-legend .credit_union{color:#8d6e8f}.mf-legend .kfcc{color:#6f8b7d}
  .mf-structure{display:grid;grid-template-columns:1fr 1fr;gap:7px}.mf-structure>div{padding:10px;border:1px solid var(--line-soft);border-radius:9px;background:var(--surface-2)}.mf-structure span{display:block;color:var(--ink-3);font-size:9.5px}.mf-structure b{display:block;margin-top:2px;font:800 14px var(--mono)}.mf-maturity{margin-top:10px}.mf-maturity>span{display:block;margin-bottom:5px;color:var(--ink-2);font-size:10px;font-weight:750}.mf-stack{display:flex;height:10px;border-radius:999px;overflow:hidden;background:#eee8ef}.mf-stack i:nth-child(1){background:#ad7190}.mf-stack i:nth-child(2){background:#c995ac}.mf-stack i:nth-child(3){background:#72547d}.mf-stack i:nth-child(4){background:#9e8aa6}.mf-stack i:nth-child(5){background:#c6b8ca}.mf-maturity-list{display:grid;gap:3px;margin-top:7px;color:var(--ink-3);font-size:9px}.mf-maturity-list div{display:flex;justify-content:space-between;gap:8px}.mf-maturity-list b{color:var(--ink-2);font:700 9px var(--mono)}
  .mf-note{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:10px 1px 0;color:var(--ink-3);font-size:9.5px;line-height:1.5}.mf-note strong{color:var(--ink-2)}
  @media(max-width:1000px){.mf-cards{grid-template-columns:1fr 1fr}.mf-main{grid-template-columns:1fr}}
  @media(max-width:620px){.mf-preview{padding:13px}.mf-head{flex-direction:column}.mf-badges{justify-content:flex-start}.mf-cards{grid-template-columns:1fr}.mf-card .rates{grid-template-columns:1fr 1fr}.mf-chart{height:160px}}
</style>
""".strip()

_STRATEGY_STYLE = """
<style id="strategy-market-funding-preview-style">
  .smf{margin:12px 0;padding:13px 14px;border:1px solid rgba(128,200,166,.16);border-radius:14px;background:linear-gradient(145deg,rgba(21,44,36,.76),rgba(9,25,20,.76));box-shadow:0 10px 28px rgba(0,0,0,.12)}.smf-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:9px}.smf-head b{font-size:11px}.smf-head p{margin:2px 0 0;color:#71847a;font-size:9px}.smf-head a{color:#a7cab8;text-decoration:none;font-size:9px;border-bottom:1px solid rgba(167,202,184,.25);white-space:nowrap}.smf-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}.smf-item{min-width:0;padding:9px 10px;border:1px solid rgba(213,225,219,.08);border-radius:10px;background:rgba(4,14,11,.22)}.smf-item span{display:block;color:#72877c;font-size:8.5px}.smf-item strong{display:block;margin-top:2px;color:#dce8e1;font:780 13px var(--mono)}.smf-item small{display:block;margin-top:4px;color:#64786e;font-size:8.5px;line-height:1.45}.smf-item .up{color:#d9a084}.smf-item .down{color:#8fc8aa}.smf-foot{margin:8px 1px 0;color:#62766c;font-size:8.5px;line-height:1.5}.smf-foot b{color:#91a79c}.smf .lead{color:#d4b36f}
  @media(max-width:900px){.smf-grid{grid-template-columns:1fr 1fr}}
  @media(max-width:520px){.smf-head{flex-direction:column}.smf-grid{grid-template-columns:1fr}}
</style>
""".strip()


def preview_enabled() -> bool:
    return os.getenv(PREVIEW_ENV, "").strip().lower() in _TRUE_VALUES


def load_preview_snapshot(path: Path = DEFAULT_SNAPSHOT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("purpose") != "preview_only_verified_d0_snapshot":
        raise ValueError("market-funding preview snapshot purpose mismatch")
    if payload.get("schema_version") != 1:
        raise ValueError("market-funding preview snapshot schema mismatch")
    return payload


def _month(value: str) -> str:
    return f"{value[:4]}.{value[4:6]}"


def _series(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    try:
        return snapshot["series"][key]
    except KeyError as exc:
        raise ValueError(f"market-funding preview series missing: {key}") from exc


def _points(snapshot: dict[str, Any], key: str) -> list[tuple[str, float]]:
    values = _series(snapshot, key).get("values") or []
    return [(str(month), float(value)) for month, value in values]


def _value_at(snapshot: dict[str, Any], key: str, month: str) -> float:
    for row_month, value in _points(snapshot, key):
        if row_month == month:
            return value
    raise ValueError(f"market-funding preview month missing: {key}/{month}")


def _previous_value(snapshot: dict[str, Any], key: str, month: str) -> float:
    values = _points(snapshot, key)
    for index, (row_month, _value) in enumerate(values):
        if row_month == month and index > 0:
            return values[index - 1][1]
    raise ValueError(f"market-funding preview previous month missing: {key}/{month}")


def _change_pct(current: float, previous: float) -> float:
    if previous == 0:
        raise ValueError("market-funding preview previous balance is zero")
    return (current / previous - 1) * 100


def _bp(current: float, previous: float) -> int:
    return round((current - previous) * 100)


def _delta_class(value: float) -> str:
    return "up" if value > 0 else "down" if value < 0 else "flat"


def _signed(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}"


def _sector_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    analysis_month = str(snapshot["analysis_month"])
    leading_month = str(snapshot["leading_rate_month"])
    rows: list[dict[str, Any]] = []
    for key, label, balance_key, rate_key in _SECTORS:
        balance = _value_at(snapshot, balance_key, analysis_month)
        balance_prev = _previous_value(snapshot, balance_key, analysis_month)
        balance_change = _change_pct(balance, balance_prev)
        analysis_rate = _value_at(snapshot, rate_key, analysis_month)
        leading_rate = _value_at(snapshot, rate_key, leading_month)
        rows.append(
            {
                "key": key,
                "label": label,
                "balance": balance,
                "balance_change": balance_change,
                "analysis_rate": analysis_rate,
                "leading_rate": leading_rate,
                "leading_bp": _bp(leading_rate, analysis_rate),
            }
        )
    return rows


def _index_chart(snapshot: dict[str, Any]) -> str:
    width = 820.0
    height = 188.0
    left = 36.0
    right = 10.0
    top = 12.0
    bottom = 22.0
    balance_keys = {
        "bank": "bank_total_deposit_balance_eom",
        "savings_bank": "savings_bank_deposit_balance_eom",
        "credit_union": "credit_union_deposit_balance_eom",
        "kfcc": "kfcc_deposit_balance_eom",
    }
    normalized: dict[str, list[tuple[str, float]]] = {}
    all_values: list[float] = []
    for key, source_key in balance_keys.items():
        points = _points(snapshot, source_key)
        base = points[0][1]
        indexed = [(month, value / base * 100) for month, value in points]
        normalized[key] = indexed
        all_values.extend(value for _month_value, value in indexed)
    low = min(all_values)
    high = max(all_values)
    pad = max((high - low) * 0.12, 1.0)
    low -= pad
    high += pad
    plot_width = width - left - right
    plot_height = height - top - bottom

    def xy(index: int, value: float, count: int) -> tuple[float, float]:
        x = left + (plot_width * index / max(count - 1, 1))
        y = top + (high - value) / (high - low) * plot_height
        return x, y

    paths: list[str] = []
    for key, values in normalized.items():
        coords = [xy(i, value, len(values)) for i, (_month_value, value) in enumerate(values)]
        d = " ".join(
            ("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}"
            for i, (x, y) in enumerate(coords)
        )
        paths.append(f'<path class="mf-line {key}" d="{d}"/>')

    grid = []
    for fraction in (0.0, 0.5, 1.0):
        y = top + plot_height * fraction
        value = high - (high - low) * fraction
        grid.append(
            f'<line class="mf-gridline" x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}"/>'
            f'<text class="mf-axis" x="0" y="{y+3:.1f}">{value:.0f}</text>'
        )
    months = normalized["bank"]
    for index in (0, len(months) // 2, len(months) - 1):
        x, _y = xy(index, 100.0, len(months))
        grid.append(
            f'<text class="mf-axis" x="{x:.1f}" y="{height-4}" text-anchor="middle">{html.escape(_month(months[index][0]))}</text>'
        )
    return "".join(grid + paths)


def _maturity(snapshot: dict[str, Any]) -> list[tuple[str, float, float]]:
    analysis_month = str(snapshot["analysis_month"])
    keys = (
        ("6개월 미만", "bank_term_deposit_lt_6m_eom"),
        ("6~12개월", "bank_term_deposit_6m_lt_1y_eom"),
        ("1~2년", "bank_term_deposit_1y_lt_2y_eom"),
        ("2~3년", "bank_term_deposit_2y_lt_3y_eom"),
        ("3년 이상", "bank_term_deposit_3y_plus_eom"),
    )
    values = [(label, _value_at(snapshot, key, analysis_month)) for label, key in keys]
    total = sum(value for _label, value in values)
    return [(label, value, value / total * 100) for label, value in values]


def inject_search_market_funding_preview(
    page_html: str,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Inject the full macro/current-status module into Search preview only."""
    if SEARCH_MARKER in page_html:
        return page_html
    if "</head>" not in page_html or "</header>" not in page_html:
        raise ValueError("Search preview insertion point missing")
    snapshot = snapshot or load_preview_snapshot()
    analysis_month = str(snapshot["analysis_month"])
    leading_month = str(snapshot["leading_rate_month"])
    rows = _sector_rows(snapshot)
    cards = []
    for row in rows:
        delta_class = _delta_class(row["balance_change"])
        cards.append(
            f'''<article class="mf-card"><div class="sector"><span>{html.escape(row['label'])}</span><b class="delta {delta_class}">{_signed(row['balance_change'])}%</b></div><strong class="balance">{row['balance']:,.2f}<small>조</small></strong><div class="rates"><div><span>{_month(analysis_month)} 실현 1년</span><b>{row['analysis_rate']:.2f}%</b></div><div><span>{_month(leading_month)} 최신 금리</span><b class="lead">{row['leading_rate']:.2f}% · {row['leading_bp']:+d}bp</b></div></div></article>'''
        )
    term_deposit = _value_at(snapshot, "bank_term_deposit_balance_eom", analysis_month)
    installment = _value_at(snapshot, "bank_installment_savings_balance_eom", analysis_month)
    maturity = _maturity(snapshot)
    stack = "".join(f'<i style="width:{share:.3f}%"></i>' for _label, _value, share in maturity)
    maturity_rows = "".join(
        f'<div><span>{html.escape(label)}</span><b>{value:,.1f}조 · {share:.1f}%</b></div>'
        for label, value, share in maturity
    )
    section = f'''
<section class="mf-preview" id="market-funding-preview" aria-label="수신시장 현황 미리보기">
  <div class="mf-head"><div><h2>수신시장 현황</h2><p>공시상품을 보기 전에 업권별 자금 규모·방향과 실제 신규취급 금리를 먼저 확인합니다.</p></div><div class="mf-badges"><span class="mf-badge">ECOS · 월말 말잔</span><span class="mf-badge">분석 기준 {_month(analysis_month)}</span><span class="mf-badge lead">금리 선행 {_month(leading_month)}</span></div></div>
  <div class="mf-cards">{''.join(cards)}</div>
  <div class="mf-main">
    <article class="mf-panel"><div class="mf-panel-head"><b>업권별 수신잔액 추이</b><span>최근 12개월 · 각 업권 시작월=100</span></div><svg class="mf-chart" viewBox="0 0 820 188" preserveAspectRatio="none" role="img" aria-label="예금은행, 저축은행, 신협, 새마을금고 수신잔액 지수 추이">{_index_chart(snapshot)}</svg><div class="mf-legend"><span class="bank"><i></i>예금은행</span><span class="savings_bank"><i></i>저축은행</span><span class="credit_union"><i></i>신협</span><span class="kfcc"><i></i>새마을금고</span></div></article>
    <article class="mf-panel"><div class="mf-panel-head"><b>예금은행 수신 구조</b><span>{_month(analysis_month)} 말잔</span></div><div class="mf-structure"><div><span>정기예금</span><b>{term_deposit:,.1f}조</b></div><div><span>정기적금</span><b>{installment:,.1f}조</b></div></div><div class="mf-maturity"><span>정기예금 만기 구조</span><div class="mf-stack">{stack}</div><div class="mf-maturity-list">{maturity_rows}</div></div></article>
  </div>
  <div class="mf-note"><span><strong>해석:</strong> 잔액 증감은 신규 순유입과 동일하지 않으며 업권 간 자금이동을 직접 뜻하지 않습니다.</span><span>금리=신규취급액 가중평균 · 잔액=월말 말잔 · D0 exact-run #{snapshot['source_run']}</span></div>
</section>
'''.strip()
    rendered = page_html.replace("</head>", _SEARCH_STYLE + "\n</head>", 1)
    return rendered.replace("</header>", "</header>\n" + section, 1)


def inject_strategy_market_funding_preview(
    page_html: str,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Inject only a compact market-context strip into Strategy preview."""
    if STRATEGY_MARKER in page_html:
        return page_html
    if "</head>" not in page_html or "</header>" not in page_html:
        raise ValueError("Strategy preview insertion point missing")
    snapshot = snapshot or load_preview_snapshot()
    analysis_month = str(snapshot["analysis_month"])
    leading_month = str(snapshot["leading_rate_month"])
    items = []
    for row in _sector_rows(snapshot):
        delta_class = _delta_class(row["balance_change"])
        items.append(
            f'''<div class="smf-item"><span>{html.escape(row['label'])} · {_month(analysis_month)} 말잔</span><strong>{row['balance']:,.2f}조 <em class="{delta_class}" style="font-style:normal;font-size:.7em">{_signed(row['balance_change'])}%</em></strong><small>실현 1년 {row['analysis_rate']:.2f}% → <b class="lead">{_month(leading_month)} {row['leading_rate']:.2f}% ({row['leading_bp']:+d}bp)</b></small></div>'''
        )
    section = f'''
<section class="smf" id="strategy-market-funding-preview" aria-label="수신시장 환경 요약 미리보기">
  <div class="smf-head"><div><b>시장 환경 요약</b><p>전략에서는 거시 흐름을 압축하고, 경쟁 공시금리·당사 포지션·상품기획에 집중합니다.</p></div><a href="./#market-funding-preview">수신시장 현황 전체 보기 →</a></div>
  <div class="smf-grid">{''.join(items)}</div>
  <div class="smf-foot"><b>공통 분석월 {_month(analysis_month)}</b> · 최신 금리 {_month(leading_month)}는 선행신호로 분리 · 잔액 변화와 금리 변화의 인과관계는 단정하지 않음</div>
</section>
'''.strip()
    rendered = page_html.replace("</head>", _STRATEGY_STYLE + "\n</head>", 1)
    return rendered.replace("</header>", "</header>\n" + section, 1)
