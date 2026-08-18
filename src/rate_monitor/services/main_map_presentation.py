"""메인 대시보드 권역 타일을 대한민국 지도 presentation으로 바꾼다.

계산 계약은 건드리지 않는다. ``site.html``의 ``regionBars()``가 기존과 똑같이
``regionRows()``를 계산해 ``.regtile``을 만든 뒤, 이 모듈이 주입한 브라우저
presentation이 그 **이미 계산된 타일 DOM만 읽어** 지도에 옮긴다.

이 경계를 지키는 이유는 두 가지다.

1. 권역 중앙값·필터 반응성·부산 drill-down은 이미 안정화된 계약이다.
2. ``web/assets/korea-sido.svg``의 배포본은 Strategy Release Gate에 묶여 있다.
   메인 공개 화면이 그 산출물에 의존하면 Gate OFF에서 지도가 깨진다.

따라서 source SVG geometry는 빌드 시 메인 HTML의 ``<template>``에 인라인한다.
Strategy 산출물 ``assets/korea-sido.svg``의 발행/삭제 정책은 전혀 바꾸지 않는다.
"""

from __future__ import annotations

import re

from rate_monitor.services.dashboard_service import DashboardBuildError

MAIN_MAP_MARKER = 'data-main-korea-map-presentation="1"'
MAIN_MAP_TEMPLATE_ID = "main-korea-map-svg"

MAIN_MAP_STYLE = r"""
<style data-main-korea-map-presentation="1">
  .regtiles.main-korea-map { display: block; }
  .main-map-shell {
    display: grid;
    grid-template-columns: minmax(0, 1.38fr) minmax(230px, .62fr);
    gap: 16px;
    margin-top: 4px;
    align-items: stretch;
  }
  .main-map-stage {
    position: relative;
    min-height: 430px;
    border: 1px solid var(--line-soft);
    border-radius: 14px;
    background:
      radial-gradient(circle at 48% 44%, rgba(211,58,124,.08), transparent 42%),
      linear-gradient(145deg, #FFFCFE, var(--surface-2));
    overflow: hidden;
  }
  .main-map-stage svg {
    display: block;
    width: 100%;
    height: 100%;
    max-height: 520px;
    padding: 16px 20px;
  }
  .main-map-stage svg g { fill: none; }
  .main-map-stage svg path {
    stroke: rgba(91,47,100,.28);
    stroke-width: 1.15;
    vector-effect: non-scaling-stroke;
    transition: filter .14s ease, opacity .14s ease, stroke .14s ease;
    outline: none;
  }
  .main-map-stage svg path[data-has-rate="1"] { cursor: default; }
  .main-map-stage svg path[data-region-key="부산"] { cursor: pointer; }
  .main-map-stage svg path:hover,
  .main-map-stage svg path:focus-visible,
  .main-map-stage svg path.is-selected {
    stroke: var(--accent-ink);
    stroke-width: 2.2;
    filter: drop-shadow(0 5px 8px rgba(91,47,100,.18));
  }
  .main-map-stage svg path[data-region-key="부산"] {
    stroke: var(--crit);
    stroke-width: 1.8;
  }
  .main-map-tooltip {
    position: absolute;
    z-index: 3;
    min-width: 150px;
    max-width: 230px;
    padding: 9px 10px;
    border: 1px solid rgba(91,47,100,.18);
    border-radius: 9px;
    background: rgba(255,255,255,.96);
    color: var(--ink);
    box-shadow: 0 10px 28px rgba(69,39,71,.16);
    pointer-events: none;
    transform: translate(10px, 10px);
    font-size: 11px;
    line-height: 1.5;
  }
  .main-map-tooltip[hidden] { display: none; }
  .main-map-tooltip b { display:block; margin-bottom:2px; font-size:12px; }
  .main-map-tooltip .mv { color:var(--accent-ink); font:800 17px/1.25 var(--mono); }
  .main-map-side {
    min-width: 0;
    padding: 16px;
    border: 1px solid var(--line-soft);
    border-radius: 14px;
    background: linear-gradient(150deg, #FFFFFF, #FBF7FA);
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .main-map-side .eyebrow {
    color: var(--ink-3);
    font-size: 10px;
    font-weight: 750;
    letter-spacing: .04em;
  }
  .main-map-side h3 { margin: 0; font-size: 18px; letter-spacing: -.02em; }
  .main-map-rate {
    color: var(--accent-ink);
    font: 850 32px/1 var(--mono);
    letter-spacing: -.04em;
  }
  .main-map-rate small { margin-left:2px; font-size:.46em; font-weight:700; }
  .main-map-meta { color: var(--ink-2); font-size: 11px; line-height: 1.65; }
  .main-map-meta b { color: var(--ink); }
  .main-map-top {
    margin-top: auto;
    padding-top: 11px;
    border-top: 1px solid var(--line-soft);
  }
  .main-map-top .tt { margin-bottom: 6px; color: var(--ink-3); font-size: 10px; font-weight: 750; }
  .main-map-top ol { margin:0; padding:0; list-style:none; display:grid; gap:5px; }
  .main-map-top li { display:flex; gap:8px; justify-content:space-between; font-size:11px; }
  .main-map-top li b { font-family:var(--mono); color:var(--accent-ink); }
  .main-map-hint { color: var(--ink-3); font-size: 10px; line-height: 1.55; }
  @media (max-width: 800px) {
    .main-map-shell { grid-template-columns: 1fr; }
    .main-map-stage { min-height: 360px; }
    .main-map-stage svg { max-height: 430px; padding: 12px; }
    .main-map-side { min-height: 0; }
  }
  @media (max-width: 480px) {
    .main-map-stage { min-height: 315px; }
    .main-map-stage svg { padding: 8px 2px; }
    .main-map-side { padding: 13px; }
    .main-map-rate { font-size: 28px; }
  }
</style>
""".strip()

MAIN_MAP_SCRIPT = r"""
<script data-main-korea-map-presentation="1">
(() => {
  const TEMPLATE_ID = "main-korea-map-svg";
  const reg = document.getElementById("reg");
  if (!reg) return;

  // SVG는 17개 시도, 기존 통계는 9개 권역이다. 시도별 새 통계를 만들지 않고
  // 기존 권역값을 해당 시도 path에 그대로 칠한다.
  const REGION_BY_SVG_ID = {
    "서울특별시":"서울",
    "인천광역시":"인천·경기", "경기도":"인천·경기",
    "강원도":"강원", "강원특별자치도":"강원",
    "대전광역시":"충청", "세종특별자치시":"충청",
    "충청북도":"충청", "충청남도":"충청",
    "광주광역시":"전라", "전라북도":"전라", "전북특별자치도":"전라",
    "전라남도":"전라", "전남광주통합특별시":"전라",
    "대구광역시":"경북", "경상북도":"경북",
    "울산광역시":"경남", "경상남도":"경남",
    "부산광역시":"부산",
    "제주특별자치도":"제주", "제주도":"제주"
  };

  const cleanName = (text) => String(text || "").replace(/\s*▾\s*$/, "").trim();
  const num = (value) => Number.parseFloat(String(value || "").replace(/[^0-9.+-]/g, ""));
  const tileData = () => [...reg.querySelectorAll(".regtile")].map((tile) => {
    const valueEl = tile.querySelector(".vl");
    const thin = !!tile.querySelector(".vl.thin");
    const value = thin ? null : num(valueEl && valueEl.textContent);
    return {
      name: cleanName(tile.querySelector(".rg")?.textContent),
      value: Number.isFinite(value) ? value : null,
      thin,
      mine: tile.classList.contains("mine"),
      drill: tile.hasAttribute("data-drill"),
      gap: tile.querySelector(".gap")?.textContent?.trim() || "",
      count: tile.querySelector(".ct")?.textContent?.trim() || "",
      band: tile.querySelector(".bd")?.textContent?.trim() || ""
    };
  }).filter((d) => d.name);

  // 메인 디자인의 핑크-퍼플 한 계열만 사용한다. 값이 높을수록 채도를 올리되
  // 길이/면적을 수치처럼 읽게 하지 않는다.
  const heatFill = (t) => {
    const p = Math.max(0, Math.min(1, t));
    const a = [247, 235, 242], b = [183, 65, 116];
    const rgb = a.map((v, i) => Math.round(v + (b[i] - v) * p));
    return `rgb(${rgb.join(",")})`;
  };

  const regionForPath = (id) => {
    if (REGION_BY_SVG_ID[id]) return REGION_BY_SVG_ID[id];
    if (id.startsWith("서울")) return "서울";
    if (id.startsWith("인천") || id.startsWith("경기")) return "인천·경기";
    if (id.startsWith("강원")) return "강원";
    if (/^(대전|세종|충청)/.test(id)) return "충청";
    if (/^(광주|전라|전북|전남)/.test(id)) return "전라";
    if (/^(대구|경상북)/.test(id)) return "경북";
    if (/^(울산|경상남)/.test(id)) return "경남";
    if (id.startsWith("부산")) return "부산";
    if (id.startsWith("제주")) return "제주";
    return null;
  };

  let selected = "부산";
  let rendering = false;

  const renderSide = (side, data, all) => {
    const target = data || all.find((d) => d.name === "부산") || all.find((d) => d.value != null) || all[0];
    if (!target) return;
    selected = target.name;
    const top = all.filter((d) => d.value != null).slice().sort((a,b) => b.value - a.value).slice(0, 4);
    side.innerHTML = `
      <div class="eyebrow">현재 권역 근거</div>
      <h3>${target.name}</h3>
      <div class="main-map-rate">${target.value == null ? "—" : target.value.toFixed(2) + "<small>%</small>"}</div>
      <div class="main-map-meta">
        ${target.thin ? "표본이 적어 중앙값 구간을 안정적으로 계산하지 못했습니다." : "조회 조건 기준 최고금리 <b>중앙값</b>"}
        ${target.count ? `<br>${target.count}` : ""}
        ${target.gap ? `<br>당사 중앙값 대비 <b>${target.gap}</b>` : ""}
        ${target.band ? `<br>중앙값 흔들림 ${target.band}` : ""}
      </div>
      <div class="main-map-top"><div class="tt">현재 조건 중앙값 상단</div><ol>
        ${top.map((d) => `<li><span>${d.name}</span><b>${d.value.toFixed(2)}%</b></li>`).join("")}
      </ol></div>
      <div class="main-map-hint">지도 색은 기존 권역 중앙값을 시도 경계에 표시한 것입니다. 시도별 새 통계를 계산하지 않습니다.${target.drill ? " 부산을 누르면 기존 구·군 상세로 이동합니다." : ""}</div>`;
  };

  const showTooltip = (tip, data, event) => {
    tip.innerHTML = `<b>${data.name}</b>`
      + `<span class="mv">${data.value == null ? "표본 부족" : data.value.toFixed(2) + "%"}</span>`
      + (data.count ? `<br>${data.count}` : "")
      + (data.gap ? `<br>당사 대비 ${data.gap}` : "")
      + (data.band ? `<br>흔들림 ${data.band}` : "");
    tip.hidden = false;
    const box = reg.getBoundingClientRect();
    tip.style.left = `${Math.max(6, Math.min(box.width - 220, event.clientX - box.left))}px`;
    tip.style.top = `${Math.max(6, event.clientY - box.top)}px`;
  };

  const transform = () => {
    if (rendering) return;
    const title = document.getElementById("reg-title")?.textContent || "";
    // 부산 구·군은 polygon asset이 없고 기존 타일 drill-down이 안정화되어 있다.
    if (title.includes("부산 구·군별")) {
      reg.classList.remove("main-korea-map");
      return;
    }
    const all = tileData();
    if (!all.length) return;
    const tpl = document.getElementById(TEMPLATE_ID);
    const sourceSvg = tpl?.content?.querySelector("svg");
    if (!sourceSvg) return;

    const values = all.filter((d) => d.value != null).map((d) => d.value);
    const lo = values.length ? Math.min(...values) : 0;
    const hi = values.length ? Math.max(...values) : 0;
    const byName = new Map(all.map((d) => [d.name, d]));

    const shell = document.createElement("div");
    shell.className = "main-map-shell";
    const stage = document.createElement("div");
    stage.className = "main-map-stage";
    const side = document.createElement("aside");
    side.className = "main-map-side";
    side.setAttribute("aria-live", "polite");
    const tip = document.createElement("div");
    tip.className = "main-map-tooltip";
    tip.hidden = true;

    const svg = sourceSvg.cloneNode(true);
    svg.removeAttribute("width"); svg.removeAttribute("height");
    svg.setAttribute("aria-label", "대한민국 권역별 최고금리 중앙값 지도");
    svg.querySelectorAll("path[id]").forEach((path) => {
      const region = regionForPath(path.id || "");
      const d = region ? byName.get(region) : null;
      path.dataset.regionKey = region || "";
      path.dataset.hasRate = d && d.value != null ? "1" : "0";
      path.style.fill = !d || d.value == null
        ? "#F1ECF2"
        : heatFill(hi > lo ? (d.value - lo) / (hi - lo) : .55);
      path.style.opacity = d ? "1" : ".58";
      if (!d) {
        path.setAttribute("aria-label", `${region || path.id}: 현재 조건 지역 데이터 없음`);
        return;
      }
      path.setAttribute("tabindex", "0");
      path.setAttribute("aria-label", `${d.name} 중앙값 ${d.value == null ? "표본 부족" : d.value.toFixed(2) + "%"}`);
      if (d.drill) path.setAttribute("data-drill", "1");
      const activate = () => {
        svg.querySelectorAll("path.is-selected").forEach((p) => p.classList.remove("is-selected"));
        svg.querySelectorAll(`path[data-region-key="${d.name}"]`).forEach((p) => p.classList.add("is-selected"));
        renderSide(side, d, all);
      };
      path.addEventListener("mouseenter", (e) => { activate(); showTooltip(tip, d, e); });
      path.addEventListener("mousemove", (e) => showTooltip(tip, d, e));
      path.addEventListener("mouseleave", () => { tip.hidden = true; });
      path.addEventListener("focus", () => activate());
      path.addEventListener("keydown", (e) => {
        if ((e.key === "Enter" || e.key === " ") && d.drill) {
          e.preventDefault(); path.dispatchEvent(new MouseEvent("click", { bubbles:true }));
        }
      });
    });

    stage.append(svg, tip);
    shell.append(stage, side);
    renderSide(side, byName.get(selected), all);
    const chosen = selected && svg.querySelectorAll(`path[data-region-key="${selected}"]`);
    chosen && chosen.forEach((p) => p.classList.add("is-selected"));

    rendering = true;
    reg.classList.add("main-korea-map");
    reg.style.gridTemplateColumns = "";
    reg.replaceChildren(shell);
    reg.setAttribute("aria-label", "권역별 최고금리 중앙값 대한민국 지도");
    rendering = false;
  };

  new MutationObserver(transform).observe(reg, { childList:true });
  queueMicrotask(transform);
})();
</script>
""".strip()


def _svg_for_template(svg_markup: str) -> str:
    """XML 선언만 제거해 HTML ``template`` 안에 안전하게 넣는다."""
    text = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", svg_markup, count=1)
    if "<svg" not in text or "</svg>" not in text:
        raise DashboardBuildError("메인 지도 source SVG가 유효하지 않다")
    return text


def inject_main_map_presentation(html: str, svg_markup: str) -> str:
    """메인 HTML에 지도 style, source geometry template, behavior를 주입한다.

    같은 HTML을 두 번 통과시켜도 한 벌만 남는 idempotent 변환이다.
    """
    if MAIN_MAP_MARKER in html:
        return html
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("메인 지도 presentation을 넣을 HTML 경계를 찾지 못했다")

    template = (
        f'<template id="{MAIN_MAP_TEMPLATE_ID}" {MAIN_MAP_MARKER}>'
        + _svg_for_template(svg_markup)
        + "</template>"
    )
    html = html.replace("</head>", MAIN_MAP_STYLE + "\n</head>", 1)
    html = html.replace(
        "</body>", template + "\n" + MAIN_MAP_SCRIPT + "\n</body>", 1
    )
    return html
