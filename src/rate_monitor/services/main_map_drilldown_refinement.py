# ruff: noqa: E501
"""메인 검색 화면의 전국/부산 지도 presentation 보정.

이 계층은 기존 ``site.html``이 계산한 권역/구·군 중앙값 타일 DOM만 읽는다.
새 금리 집계, source precedence, stable identity, DB 계약을 만들지 않는다.

presentation 책임은 네 가지다.

1. 전국 지도는 본토 + 제주 본섬 중심으로 군소 도서 subpath를 생략하고 viewBox를
   다시 맞춰 비교용 지도를 더 크게 읽히게 한다.
2. 데스크톱에서 세로형 전국 지도가 불필요하게 넓은 카드 폭을 차지하지 않되,
   100% 브라우저 배율에서 너무 작아지지 않도록 적정 읽기 크기를 유지한다.
3. 제주 등 하단 권역 tooltip이 지도 stage 밖으로 잘리지 않도록 flip + clamp한다.
4. 부산 drill-down은 기존 16개 네모 타일 대신 Strategy에서 이미 사용하는
   SGIS 2020 부산 구·군 경계 geometry 위에 같은 중앙값을 표시한다.

전국 source SVG 자체는 수정하지 않는다. 브라우저에 인라인된 clone에서 각 시도의
가장 큰 polygon subpath만 남기므로 울릉도·독도와 서해/동해 군소 도서는 검색 비교
화면에서 생략되지만 제주특별자치도의 가장 큰 본섬은 유지된다.

부산 geometry도 Strategy **배포 산출물**에 의존하지 않는다. 저장소의
``web/templates/strategy.html`` source에 있는 ``BUSAN_BOUNDARY_SVG``를 빌드 시
추출해 메인 HTML ``template`` 안에 인라인한다. 따라서 Strategy Release Gate를
켜거나 ``assets/``를 공개하지 않아도 검색 화면이 독립적으로 동작한다.
"""

from __future__ import annotations

import re

from rate_monitor.services.dashboard_service import DashboardBuildError

MAIN_MAP_DRILLDOWN_MARKER = 'data-main-map-drilldown-refinement="1"'
BUSAN_TEMPLATE_ID = "main-busan-map-svg"

_STYLE = r"""
<style data-main-map-drilldown-refinement="1">
  /* Desktop: 본토+제주 crop은 유지하되 100% zoom에서 한 단계 크게 읽힌다. */
  .charts .card.wide.global {
    width: 100%;
    max-width: 980px;
    margin-inline: auto;
  }
  .charts .card.wide.global.main-national-map-card {
    max-width: 740px;
  }
  .main-map-shell,
  .main-busan-map-shell {
    display: grid;
    justify-content: center;
    gap: 12px !important;
    align-items: stretch;
  }
  .main-map-shell {
    grid-template-columns: minmax(0, 460px) minmax(190px, 220px) !important;
  }
  .main-busan-map-shell {
    grid-template-columns: minmax(0, 700px) minmax(190px, 220px) !important;
  }
  .main-map-stage {
    min-height: 460px !important;
  }
  .main-map-stage svg {
    max-height: 490px !important;
  }

  .main-busan-stage {
    position: relative;
    min-height: 470px;
    border: 1px solid var(--line-soft);
    border-radius: 14px;
    overflow: hidden;
    background:
      radial-gradient(circle at 52% 48%, rgba(211,58,124,.055), transparent 48%),
      linear-gradient(145deg, #FFFCFE, var(--surface-2));
  }
  .main-busan-stage svg {
    display: block;
    width: 100%;
    height: 100%;
    max-height: 500px;
    padding: 10px;
  }
  .main-busan-stage path {
    stroke: rgba(91,47,100,.30);
    stroke-width: 1.25;
    vector-effect: non-scaling-stroke;
    outline: none;
    transition: filter .14s ease, stroke .14s ease, opacity .14s ease;
  }
  .main-busan-stage path[data-has-rate="0"] { fill: #F1ECF2; opacity: .62; }
  .main-busan-stage path:hover,
  .main-busan-stage path:focus-visible,
  .main-busan-stage path.is-selected {
    stroke: var(--accent-ink);
    stroke-width: 2.2;
    filter: drop-shadow(0 4px 7px rgba(91,47,100,.18));
  }
  .main-busan-label-layer { pointer-events: none; }
  .main-busan-label-line {
    stroke: rgba(91,47,100,.32);
    stroke-width: 1.15;
    stroke-dasharray: 3 3;
    vector-effect: non-scaling-stroke;
  }
  .main-busan-label-name,
  .main-busan-label-rate {
    paint-order: stroke;
    stroke: rgba(255,255,255,.97);
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .main-busan-label-name {
    fill: #413343;
    stroke-width: 4px;
    font: 820 15px var(--sans);
  }
  .main-busan-label-rate {
    fill: #5B2F64;
    stroke-width: 4px;
    font: 900 16px var(--mono);
  }
  .main-busan-label-rate.is-thin {
    fill: #8A7E8C;
    font: 760 12px var(--sans);
  }
  .main-busan-side {
    min-width: 0;
    padding: 13px;
    border: 1px solid var(--line-soft);
    border-radius: 14px;
    background: linear-gradient(150deg, #FFFFFF, #FBF7FA);
    display: flex;
    flex-direction: column;
    gap: 9px;
  }
  .main-busan-side .eyebrow {
    color: var(--ink-3);
    font-size: 10px;
    font-weight: 760;
    letter-spacing: .04em;
  }
  .main-busan-side h3 { margin: 0; font-size: 16px; }
  .main-busan-rate {
    color: var(--accent-ink);
    font: 850 28px/1 var(--mono);
    letter-spacing: -.035em;
  }
  .main-busan-rate small { margin-left: 2px; font-size: .48em; }
  .main-busan-meta { color: var(--ink-2); font-size: 10px; line-height: 1.55; }
  .main-busan-top {
    margin-top: auto;
    padding-top: 9px;
    border-top: 1px solid var(--line-soft);
  }
  .main-busan-top .tt { margin-bottom: 5px; color: var(--ink-3); font-size: 10px; font-weight: 750; }
  .main-busan-top ol { margin: 0; padding: 0; list-style: none; display: grid; gap: 5px; }
  .main-busan-top li { display: flex; justify-content: space-between; gap: 7px; font-size: 10px; }
  .main-busan-top li b { color: var(--accent-ink); font-family: var(--mono); }
  .main-busan-hint { color: var(--ink-3); font-size: 9.5px; line-height: 1.45; }

  @media (max-width: 1000px) {
    .charts .card.wide.global,
    .charts .card.wide.global.main-national-map-card { max-width: none; }
    .main-map-shell,
    .main-busan-map-shell { grid-template-columns: 1fr !important; }
    .main-busan-side {
      display: grid;
      grid-template-columns: minmax(150px,.72fr) minmax(0,1.28fr);
      align-items: start;
    }
    .main-busan-side .main-busan-top { margin: 0; padding: 0; border: 0; }
    .main-busan-hint { grid-column: 1 / -1; }
  }
  @media (max-width: 760px) {
    .main-map-stage { min-height: 390px !important; }
    .main-busan-stage { min-height: 390px; }
    .main-busan-stage svg { padding: 5px; }
    .main-busan-label-name { font-size: 20px; stroke-width: 6px; }
    .main-busan-label-rate { font-size: 21px; stroke-width: 6px; }
    .main-busan-label-rate.is-thin { font-size: 17px; }
    .main-busan-side { grid-template-columns: 1fr; }
    .main-busan-hint { grid-column: auto; }
  }
  @media (max-width: 480px) {
    .main-busan-stage { min-height: 340px; }
    .main-busan-side { padding: 11px; }
  }
  @media print {
    .charts .card.wide.global,
    .charts .card.wide.global.main-national-map-card { max-width: none; }
    .main-busan-stage, .main-busan-side { box-shadow: none !important; }
  }
</style>
""".strip()

_SCRIPT = r"""
<script data-main-map-drilldown-refinement="1">
(() => {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const TEMPLATE_ID = "main-busan-map-svg";
  const reg = document.getElementById("reg");
  if (!reg) return;

  const LABEL_OFFSETS = {
    "부산진구": [-58,-26,"end"],
    "연제구": [34,-30,"start"],
    "수영구": [54,4,"start"],
    "동구": [38,-18,"start"],
    "중구": [42,18,"start"],
    "사하구": [-40,0,"end"],
    "서구": [-44,22,"end"]
  };
  const MOBILE_LABEL_OFFSETS = {
    "남구": [0,24,"middle"],
    "해운대구": [58,-8,"start"]
  };
  const cleanName = (text) => String(text || "").replace(/\s*▾\s*$/, "").trim();
  const num = (value) => Number.parseFloat(String(value || "").replace(/[^0-9.+-]/g, ""));
  const tileData = () => [...reg.querySelectorAll(":scope > .regtile")].map((tile) => {
    const valueEl = tile.querySelector(".vl");
    const thin = !!tile.querySelector(".vl.thin");
    const value = thin ? null : num(valueEl?.textContent);
    return {
      name: cleanName(tile.querySelector(".rg")?.textContent),
      value: Number.isFinite(value) ? value : null,
      thin,
      gap: tile.querySelector(".gap")?.textContent?.trim() || "",
      count: tile.querySelector(".ct")?.textContent?.trim() || "",
      band: tile.querySelector(".bd")?.textContent?.trim() || ""
    };
  }).filter((d) => d.name);

  const heatFill = (t) => {
    const p = Math.max(0, Math.min(1, t));
    const a = [247,235,242], b = [183,65,116];
    const rgb = a.map((v, i) => Math.round(v + (b[i] - v) * p));
    return `rgb(${rgb.join(",")})`;
  };

  const subpathArea = (part) => {
    const nums = String(part || "").match(/[-+]?(?:\d*\.)?\d+(?:e[-+]?\d+)?/gi) || [];
    if (nums.length < 4) return 0;
    const xs = [], ys = [];
    for (let i = 0; i + 1 < nums.length; i += 2) {
      xs.push(Number(nums[i]));
      ys.push(Number(nums[i + 1]));
    }
    if (!xs.length || !ys.length) return 0;
    return (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys));
  };

  const keepLargestSubpath = (path) => {
    const d = path.getAttribute("d") || "";
    const parts = d.match(/M[^M]+/g) || [];
    if (parts.length <= 1) return 0;
    const largest = parts.slice().sort((a,b) => subpathArea(b) - subpathArea(a))[0];
    if (largest) path.setAttribute("d", largest.trim());
    return Math.max(0, parts.length - 1);
  };

  const fitNationalTooltip = (stage) => {
    requestAnimationFrame(() => {
      const tip = stage?.querySelector(".main-map-tooltip");
      if (!tip || tip.hidden) return;
      const width = tip.offsetWidth, height = tip.offsetHeight;
      const sw = stage.clientWidth, sh = stage.clientHeight;
      if (!width || !height || !sw || !sh) return;
      const rawLeft = Number.parseFloat(tip.style.left || "50");
      const rawTop = Number.parseFloat(tip.style.top || "50");
      let left = tip.style.left.endsWith("%") ? sw * rawLeft / 100 : rawLeft;
      let top = tip.style.top.endsWith("%") ? sh * rawTop / 100 : rawTop;
      const pad = 8;
      const offset = 10;
      left += offset;
      top += offset;
      if (top + height > sh - pad) top = top - height - offset * 2;
      left = Math.max(pad, Math.min(left, sw - width - pad));
      top = Math.max(pad, Math.min(top, sh - height - pad));
      tip.style.left = `${left.toFixed(1)}px`;
      tip.style.top = `${top.toFixed(1)}px`;
      tip.style.transform = "none";
      tip.dataset.viewportFit = "1";
    });
  };

  const bindNationalTooltipClamp = () => {
    const stage = reg.querySelector(":scope .main-map-stage");
    if (!stage || stage.dataset.tooltipClampBound === "1") return;
    stage.dataset.tooltipClampBound = "1";
    stage.querySelectorAll("svg path[data-region-key]").forEach((path) => {
      path.addEventListener("mouseenter", () => fitNationalTooltip(stage));
      path.addEventListener("focus", () => fitNationalTooltip(stage));
    });
  };

  const refineNational = () => {
    const title = document.getElementById("reg-title")?.textContent || "";
    const card = reg.closest(".card.wide.global");
    if (title.includes("부산 구·군별")) {
      card?.classList.remove("main-national-map-card");
      return;
    }
    const svg = reg.querySelector(":scope .main-map-stage svg");
    if (!svg) return;
    card?.classList.add("main-national-map-card");
    reg.classList.remove("main-busan-map");
    bindNationalTooltipClamp();
    if (svg.dataset.mainlandJejuCrop === "1") return;

    let omitted = 0;
    const paths = [...svg.querySelectorAll("#전국_시도_경계 path[id]")];
    for (const path of paths) omitted += keepLargestSubpath(path);

    const boxes = paths.map((path) => path.getBBox()).filter((box) => box.width > 0 && box.height > 0);
    if (boxes.length) {
      const x1 = Math.min(...boxes.map((box) => box.x));
      const y1 = Math.min(...boxes.map((box) => box.y));
      const x2 = Math.max(...boxes.map((box) => box.x + box.width));
      const y2 = Math.max(...boxes.map((box) => box.y + box.height));
      const padX = 14, padY = 10;
      svg.setAttribute("viewBox", `${(x1-padX).toFixed(1)} ${(y1-padY).toFixed(1)} ${(x2-x1+padX*2).toFixed(1)} ${(y2-y1+padY*2).toFixed(1)}`);
      svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    }
    svg.dataset.mainlandJejuCrop = "1";
    svg.dataset.omittedIslandSubpaths = String(omitted);
  };

  const renderSide = (side, data, all) => {
    const target = data || all.find((d) => d.value != null) || all[0];
    if (!target) return;
    const top = all.filter((d) => d.value != null).slice().sort((a,b) => b.value - a.value).slice(0,5);
    side.innerHTML = `
      <div class="eyebrow">부산 구·군 근거</div>
      <h3>${target.name}</h3>
      <div class="main-busan-rate">${target.value == null ? "—" : target.value.toFixed(2) + "<small>%</small>"}</div>
      <div class="main-busan-meta">
        ${target.thin ? "표본이 적어 중앙값 구간을 안정적으로 계산하지 못했습니다." : "조회 조건 기준 최고금리 중앙값"}
        ${target.count ? `<br>${target.count}` : ""}
        ${target.gap ? `<br>당사 중앙값 대비 <b>${target.gap}</b>` : ""}
        ${target.band ? `<br>중앙값 흔들림 ${target.band}` : ""}
      </div>
      <div class="main-busan-top"><div class="tt">현재 조건 부산 상단</div><ol>
        ${top.map((d) => `<li><span>${d.name}</span><b>${d.value.toFixed(2)}%</b></li>`).join("")}
      </ol></div>
      <div class="main-busan-hint">전국 화면과 같은 조회조건을 쓰고 지역만 부산 구·군으로 나눕니다. 아래 “전국으로 돌아가기”로 전국 지도로 복귀합니다.</div>`;
  };

  const addText = (group, klass, x, y, anchor, text) => {
    const node = document.createElementNS(NS, "text");
    node.setAttribute("class", klass);
    node.setAttribute("x", x.toFixed(1));
    node.setAttribute("y", y.toFixed(1));
    node.setAttribute("text-anchor", anchor);
    node.textContent = text;
    group.appendChild(node);
  };

  let rendering = false;
  const transformBusan = () => {
    if (rendering) return;
    const title = document.getElementById("reg-title")?.textContent || "";
    if (!title.includes("부산 구·군별")) return;
    reg.closest(".card.wide.global")?.classList.remove("main-national-map-card");
    if (reg.querySelector(":scope > .main-busan-map-shell")) return;

    const all = tileData();
    if (!all.length) return;
    const tpl = document.getElementById(TEMPLATE_ID);
    const sourceSvg = tpl?.content?.querySelector("svg");
    if (!sourceSvg) return;

    const byName = new Map(all.map((d) => [d.name, d]));
    const values = all.filter((d) => d.value != null).map((d) => d.value);
    const lo = values.length ? Math.min(...values) : 0;
    const hi = values.length ? Math.max(...values) : 0;
    const svg = sourceSvg.cloneNode(true);
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    svg.setAttribute("aria-label", "부산 구·군별 최고금리 중앙값 지도");

    const shell = document.createElement("div");
    shell.className = "main-busan-map-shell";
    const stage = document.createElement("div");
    stage.className = "main-busan-stage";
    const side = document.createElement("aside");
    side.className = "main-busan-side";
    side.setAttribute("aria-live", "polite");
    stage.appendChild(svg);
    shell.append(stage, side);

    rendering = true;
    reg.classList.remove("main-korea-map");
    reg.classList.add("main-busan-map");
    reg.style.gridTemplateColumns = "";
    reg.replaceChildren(shell);
    reg.setAttribute("aria-label", "부산 구·군별 최고금리 중앙값 지도");
    rendering = false;

    const labels = document.createElementNS(NS, "g");
    labels.setAttribute("class", "main-busan-label-layer");
    labels.setAttribute("aria-hidden", "true");
    svg.appendChild(labels);

    let selected = all.find((d) => d.value != null) || all[0];
    const activate = (path, d) => {
      svg.querySelectorAll("path.is-selected").forEach((p) => p.classList.remove("is-selected"));
      path.classList.add("is-selected");
      selected = d;
      renderSide(side, d, all);
    };

    svg.querySelectorAll("#busan-boundaries path[id]").forEach((path) => {
      const d = byName.get(path.id);
      const hasRate = !!d && d.value != null;
      path.dataset.hasRate = hasRate ? "1" : "0";
      path.style.fill = hasRate
        ? heatFill(hi > lo ? (d.value - lo) / (hi - lo) : .55)
        : "#F1ECF2";
      path.style.opacity = d ? "1" : ".58";
      const aria = !d ? `${path.id}: 현재 조건 데이터 없음`
        : `${d.name} 중앙값 ${d.value == null ? "표본 부족" : d.value.toFixed(2) + "%"}`;
      path.setAttribute("aria-label", aria);
      const titleNode = document.createElementNS(NS, "title");
      titleNode.textContent = aria;
      path.prepend(titleNode);
      if (d) {
        path.setAttribute("tabindex", "0");
        path.addEventListener("mouseenter", () => activate(path, d));
        path.addEventListener("focus", () => activate(path, d));
      }

      const box = path.getBBox();
      const cx = box.x + box.width / 2;
      const cy = box.y + box.height / 2;
      const mobileOffset = window.matchMedia("(max-width: 760px)").matches
        ? MOBILE_LABEL_OFFSETS[path.id]
        : null;
      const offset = mobileOffset || LABEL_OFFSETS[path.id] || [0,0,"middle"];
      const x = cx + offset[0], y = cy + offset[1], anchor = offset[2];
      if (offset[0] || offset[1]) {
        const line = document.createElementNS(NS, "line");
        line.setAttribute("class", "main-busan-label-line");
        line.setAttribute("x1", cx.toFixed(1));
        line.setAttribute("y1", cy.toFixed(1));
        line.setAttribute("x2", x.toFixed(1));
        line.setAttribute("y2", (y - 5).toFixed(1));
        labels.appendChild(line);
      }
      addText(labels, "main-busan-label-name", x, y - (d ? 6 : 0), anchor, path.id);
      if (d) {
        addText(
          labels,
          `main-busan-label-rate${d.thin ? " is-thin" : ""}`,
          x, y + 11, anchor,
          d.value == null ? "표본 부족" : `${d.value.toFixed(2)}%`
        );
      }
    });

    const selectedPath = selected && svg.querySelector(`#busan-boundaries path[id="${CSS.escape(selected.name)}"]`);
    if (selectedPath) selectedPath.classList.add("is-selected");
    renderSide(side, selected, all);
  };

  const syncMaps = () => {
    queueMicrotask(() => {
      refineNational();
      transformBusan();
    });
  };
  new MutationObserver(syncMaps).observe(reg, { childList: true });
  syncMaps();
})();
</script>
""".strip()


def _extract_busan_boundary(strategy_template_text: str) -> str:
    match = re.search(
        r'const BUSAN_BOUNDARY_SVG=`(?P<markup><g id="busan-boundaries">.*?</g>)`;',
        strategy_template_text,
        flags=re.DOTALL,
    )
    if match is None:
        raise DashboardBuildError("Strategy 부산 구·군 SVG geometry를 찾지 못했다")
    markup = match.group("markup")
    if markup.count("<path") != 16:
        raise DashboardBuildError("Strategy 부산 구·군 SVG geometry가 16개 경계가 아니다")
    return markup


def inject_main_map_drilldown_refinement(html: str, strategy_template_text: str) -> str:
    """검색 화면에 전국 compact/crop + 부산 16구·군 SVG drill-down을 주입한다."""
    if MAIN_MAP_DRILLDOWN_MARKER in html:
        return html
    if "</head>" not in html:
        raise DashboardBuildError("메인 지도 drill-down style을 넣을 head 경계를 찾지 못했다")
    if "</body>" not in html:
        raise DashboardBuildError("메인 지도 drill-down script를 넣을 body 경계를 찾지 못했다")

    busan_boundary = _extract_busan_boundary(strategy_template_text)
    template = (
        f'<template id="{BUSAN_TEMPLATE_ID}" {MAIN_MAP_DRILLDOWN_MARKER}>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 757" '
        'preserveAspectRatio="xMidYMid meet" role="img" aria-label="부산 16개 구·군 행정경계">'
        + busan_boundary
        + "</svg></template>"
    )
    rendered = html.replace("</head>", _STYLE + "\n</head>", 1)
    return rendered.replace("</body>", template + "\n" + _SCRIPT + "\n</body>", 1)
