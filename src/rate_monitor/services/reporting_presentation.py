# ruff: noqa: E501
"""Main/Strategy 정적 화면에 현재 상태 기반 print-to-PDF 보고서를 붙인다.

서버 PDF 엔진이나 DB write를 추가하지 않는다. 브라우저가 현재 DOM 선택상태를
print-only report DOM으로 만들고 ``window.print()``를 호출한다. CSV/JSON은 Main의
machine-readable export 계약으로 그대로 남는다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="rate-reporting-style"'
MAIN_SCRIPT_MARKER = 'id="main-reporting-script"'
STRATEGY_SCRIPT_MARKER = 'id="strategy-reporting-script"'

_CSS = r"""
<style id="rate-reporting-style">
.rate-report-button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:30px;padding:6px 10px;border:1px solid rgba(255,255,255,.28);border-radius:8px;background:rgba(255,255,255,.10);color:#fff;font:760 11px/1.2 var(--sans,system-ui,sans-serif);white-space:nowrap;cursor:pointer}
.rate-report-button:hover,.rate-report-button:focus-visible{background:rgba(255,255,255,.18);outline:none}.rate-report-button:focus-visible{box-shadow:0 0 0 2px rgba(255,255,255,.40)}
.rate-report-root{display:none}
@media(max-width:760px){.rate-report-button{min-height:28px;padding:5px 8px;font-size:10px}}
@media print{
  @page{size:A4 portrait;margin:11mm}
  html,body{background:#fff!important}
  body.rate-report-printing>*:not(.rate-report-root){display:none!important}
  .rate-report-root{display:block!important;position:static!important;width:100%!important;margin:0!important;padding:0!important;color:#18131A!important;background:#fff!important;font:10.2pt/1.48 "Pretendard","Noto Sans KR","Apple SD Gothic Neo",Arial,sans-serif!important;letter-spacing:-.01em!important}
  .rate-report-header{padding:0 0 10mm;border-bottom:2px solid #5B2F64}.rate-report-header h1{margin:0;color:#251D27;font-size:20pt;line-height:1.15;letter-spacing:-.04em}.rate-report-header p{margin:3mm 0 0;color:#6E6270;font-size:9.5pt}.rate-report-meta{display:flex;flex-wrap:wrap;gap:2mm 6mm;margin-top:4mm;color:#746878;font-size:8.6pt}
  .rate-report-warning{margin:5mm 0;padding:3.5mm 4mm;border:1px solid #D6B68A;border-radius:2mm;background:#FFF9ED;color:#6D5124;font-size:9pt;line-height:1.5}.rate-report-warning strong{color:#5F4318}
  .rate-report-section{break-inside:avoid;margin:6mm 0 0}.rate-report-section h2{margin:0 0 2.5mm;padding-bottom:1.5mm;border-bottom:1px solid #D9D1DB;color:#392B3D;font-size:12pt}.rate-report-section p,.rate-report-section li{margin:0;color:#403641;font-size:9.3pt}.rate-report-lines{display:grid;gap:1.2mm}.rate-report-lines div{white-space:pre-wrap;overflow-wrap:anywhere}
  .rate-report-grid{display:grid;grid-template-columns:1fr 1fr;gap:3mm}.rate-report-card{padding:3mm;border:1px solid #DDD5DF;border-radius:2mm;background:#FCFAFC;break-inside:avoid}.rate-report-card b{display:block;margin-bottom:1mm;color:#4B3650}
  .rate-report-table{width:100%;border-collapse:collapse;table-layout:auto;font-size:8.2pt}.rate-report-table th{padding:2mm 1.5mm;border-bottom:1px solid #BFB3C2;background:#F7F2F7;color:#534557;text-align:left}.rate-report-table td{padding:1.8mm 1.5mm;border-bottom:1px solid #E8E2E9;color:#302A31;vertical-align:top;overflow-wrap:anywhere}.rate-report-table tr:nth-child(even) td{background:#FCFAFC}
  .rate-report-foot{margin-top:8mm;padding-top:3mm;border-top:1px solid #D9D1DB;color:#7C717E;font-size:8pt}
}
</style>
"""

_MAIN_JS = r"""
<script id="main-reporting-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const text=sel=>String(document.querySelector(sel)?.textContent||"").replace(/\s+/g," ").trim();
  const payload=()=>{try{return JSON.parse($("rate-monitor-data")?.textContent||"{}")}catch{return{}}};
  const clean=()=>{document.querySelector(".rate-report-root")?.remove();document.body.classList.remove("rate-report-printing")};
  const el=(tag,cls,txt)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(txt!=null)n.textContent=txt;return n};
  function section(root,title){const s=el("section","rate-report-section");s.appendChild(el("h2","",title));root.appendChild(s);return s}
  function lines(host,values){const box=el("div","rate-report-lines");values.filter(Boolean).forEach(v=>box.appendChild(el("div","",v)));host.appendChild(box)}
  function tableFrom(host,source,limit=15){
    if(!source)return;
    const srcRows=[...source.querySelectorAll("tr")];if(!srcRows.length)return;
    const table=el("table","rate-report-table"),thead=el("thead"),tbody=el("tbody");
    const header=srcRows.find(r=>r.querySelector("th"));
    if(header){const tr=el("tr");[...header.querySelectorAll("th")].forEach(c=>tr.appendChild(el("th","",c.textContent.trim())));thead.appendChild(tr);table.appendChild(thead)}
    srcRows.filter(r=>r.querySelector("td")).slice(0,limit).forEach(r=>{const tr=el("tr");[...r.querySelectorAll("td")].forEach(c=>tr.appendChild(el("td","",c.textContent.replace(/\s+/g," ").trim())));tbody.appendChild(tr)});
    if(tbody.children.length){table.appendChild(tbody);host.appendChild(table)}
  }
  function selectedConditions(){
    const mine=$("mine")?.selectedOptions?.[0]?.textContent?.trim();
    const checked=[...document.querySelectorAll('#conditions input[type="checkbox"]:checked')].map(x=>x.closest("label")?.textContent?.replace(/\s+/g," ").trim()).filter(Boolean);
    const q=$("q")?.value?.trim();
    const values=[];if(mine)values.push(`우리 회사: ${mine}`);if(q)values.push(`검색어: ${q}`);
    values.push(checked.length?`선택 체크조건: ${checked.slice(0,36).join(" · ")}${checked.length>36?` 외 ${checked.length-36}개`:""}`:"선택 체크조건: 기본/전체");
    return values;
  }
  function build(){
    clean();const data=payload(),root=el("article","rate-report-root");root.dataset.reportKind="main";
    const head=el("header","rate-report-header");head.appendChild(el("h1","","금리 조회·경쟁현황 보고서"));head.appendChild(el("p","","검색 조회 화면의 현재 필터·시장근거·지역요약·상위 결과를 출력용으로 정리했습니다."));
    const meta=el("div","rate-report-meta");meta.appendChild(el("span","",`보고서 출력: ${new Date().toLocaleString("ko-KR")}`));meta.appendChild(el("span","",`데이터 생성: ${data.generated_at||"확인 불가"}`));meta.appendChild(el("span","","화면 역할: 탐색 · 근거 · 상세 조회"));head.appendChild(meta);root.appendChild(head);
    const cond=section(root,"1. 조회 조건");lines(cond,selectedConditions());
    const market=section(root,"2. 시장 기준 요약");const marks=text("#marks");lines(market,[marks||"현재 benchmark 표시 없음",text("#sub")]);
    const region=section(root,"3. 지역 근거");const regionText=text(".main-map-side")||text("#reg");lines(region,[regionText||"현재 지역 요약 없음","전국 지도와 부산 drill-down은 검색 조회 화면의 상세 탐색 기능입니다."]);
    const results=section(root,"4. 현재 상위 조회 결과");const sourceTable=$("rows")?.closest("table");tableFrom(results,sourceTable,15);if(!results.querySelector("table"))lines(results,["현재 표시된 결과 행이 없습니다."]);
    const trust=section(root,"5. 데이터 기준");lines(trust,[text("#scale-summary"),text("#health")||text(".health"),"이 보고서는 화면 선택상태의 요약본입니다. 전체 세부 데이터 전달에는 기존 CSV/JSON 다운로드를 사용합니다."]);
    root.appendChild(el("footer","rate-report-foot","출력값은 화면에 표시된 수집 데이터 기준이며 원천별 기준일·지역 의미가 다를 수 있습니다. 중요한 금리결정 전에는 원천 공시와 데이터 기준을 함께 확인하십시오."));
    document.body.appendChild(root);return root;
  }
  function printReport(){build();document.body.classList.add("rate-report-printing");setTimeout(()=>window.print(),0)}
  function install(){if($("main-report-button"))return;const host=document.querySelector("header.top .head-right");if(!host)return;const b=el("button","rate-report-button","보고서 출력");b.id="main-report-button";b.type="button";b.addEventListener("click",printReport);host.appendChild(b);window.__rateMonitorReport={kind:"main",build,cleanup:clean}}
  window.addEventListener("afterprint",clean);if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""

_STRATEGY_JS = r"""
<script id="strategy-reporting-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const text=sel=>String(document.querySelector(sel)?.textContent||"").replace(/\s+/g," ").trim();
  const payload=()=>{try{return JSON.parse($("rate-monitor-data")?.textContent||"{}")}catch{return{}}};
  const clean=()=>{document.querySelector(".rate-report-root")?.remove();document.body.classList.remove("rate-report-printing")};
  const el=(tag,cls,txt)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(txt!=null)n.textContent=txt;return n};
  function section(root,title){const s=el("section","rate-report-section");s.appendChild(el("h2","",title));root.appendChild(s);return s}
  function lines(host,values){const box=el("div","rate-report-lines");values.filter(Boolean).forEach(v=>box.appendChild(el("div","",v)));host.appendChild(box)}
  function tableFrom(host,source,limit=12){
    if(!source)return;const srcRows=[...source.querySelectorAll("tr")];if(!srcRows.length)return;
    const table=el("table","rate-report-table"),thead=el("thead"),tbody=el("tbody"),header=srcRows.find(r=>r.querySelector("th"));
    if(header){const tr=el("tr");[...header.querySelectorAll("th")].forEach(c=>tr.appendChild(el("th","",c.textContent.trim())));thead.appendChild(tr);table.appendChild(thead)}
    srcRows.filter(r=>r.querySelector("td")).slice(0,limit).forEach(r=>{const tr=el("tr");[...r.querySelectorAll("td")].forEach(c=>tr.appendChild(el("td","",c.textContent.replace(/\s+/g," ").trim())));tbody.appendChild(tr)});
    if(tbody.children.length){table.appendChild(tbody);host.appendChild(table)}
  }
  function scopeLines(){
    const mode=document.querySelector(".mode-tab.active")?.textContent?.trim()||"선택시장 확인 불가";
    const sectors=[...document.querySelectorAll('[data-sector]:checked:not(:disabled)')].map(x=>x.closest("label")?.textContent?.replace(/\s+/g," ").trim()).filter(Boolean);
    const base=$("base-n")?.value,bonus=$("bonus-n")?.value,proposal=Number(base)+Number(bonus);
    return [`시장 범위: ${mode}`,`상호금융 포함업권: ${sectors.join(" · ")||"없음"}`,text("#planning-basis"),Number.isFinite(proposal)?`현재 제안금리: ${proposal.toFixed(2)}% (기본 ${base||"0"}% + 우대 ${bonus||"0"}%p)`:""];
  }
  function build(){
    clean();const data=payload(),root=el("article","rate-report-root");root.dataset.reportKind="strategy";
    const head=el("header","rate-report-header");head.appendChild(el("h1","","수신상품 금리결정 검토보고서"));head.appendChild(el("p","","현재 시장근거와 금리변경 stress scenario를 의사결정 순서로 정리한 검토용 보고서입니다."));
    const meta=el("div","rate-report-meta");meta.appendChild(el("span","",`보고서 출력: ${new Date().toLocaleString("ko-KR")}`));meta.appendChild(el("span","",`데이터 생성: ${data.generated_at||"확인 불가"}`));meta.appendChild(el("span","","화면 역할: 금리결정 지원"));head.appendChild(meta);root.appendChild(head);
    const warning=el("div","rate-report-warning");warning.innerHTML="<strong>내부 수신실적 미보정</strong> — 수신반응은 stress scenario이며 실제 forecast나 최적금리 확정값이 아닙니다. 목표 순수신 최소비용 최적금리는 내부 calibration과 FTP 정렬 이후에만 판단합니다.";root.appendChild(warning);
    const scope=section(root,"1. 결정 범위와 선택 조건");lines(scope,[...scopeLines(),text("#strategy-decision-boundary")]);
    const anchors=section(root,"2. 당사·시장 결정 기준선");lines(anchors,[text(".planning-strip")||"현재 planning 기준선 없음"]);
    const scenarios=section(root,"3. 금리별 수신반응 비교");tableFrom(scenarios,document.querySelector("#rate-response-body table"),12);if(!scenarios.querySelector("table"))lines(scenarios,[text("#rate-response-body")||"수신반응 계산값 없음"]);
    const market=section(root,"4. 시장 변화·외부 자금환경");lines(market,[text("#external-market-context"),text("#market-intelligence")].filter(Boolean));
    const competitors=section(root,"5. 가격결정 경쟁 기준 TOP 5");tableFrom(competitors,document.querySelector(".top5-card table"),5);if(!competitors.querySelector("table"))lines(competitors,["경쟁 기준 데이터 없음"]);
    const pref=section(root,"6. 우대조건 전략 요약");lines(pref,[text(".pref-intel")||text(".workspace-legacy-pref")||"우대조건 분석 없음"]);
    const region=section(root,"7. 지역 상세 연결");lines(region,[text("#strategy-region-bridge")||"지역 상세는 검색 조회의 전국 지도에서 확인합니다.","전국 지도 자체는 이 Strategy 보고서에 중복 포함하지 않습니다."]);
    root.appendChild(el("footer","rate-report-foot","본 보고서는 금리결정 검토자료입니다. 내부 실적 calibration 전에는 실제 순수신 forecast·1bp 증분효율·FTP 반영 최적금리를 확정하지 않습니다."));
    document.body.appendChild(root);return root;
  }
  function printReport(){build();document.body.classList.add("rate-report-printing");setTimeout(()=>window.print(),0)}
  function install(){if($("strategy-report-button"))return;const host=document.querySelector("header.topbar .meta");if(!host)return;const b=el("button","rate-report-button","보고서 출력");b.id="strategy-report-button";b.type="button";b.addEventListener("click",printReport);host.prepend(b);window.__rateMonitorReport={kind:"strategy",build,cleanup:clean}}
  window.addEventListener("afterprint",clean);if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def _inject(html: str, *, script: str, script_marker: str) -> str:
    has_style = STYLE_MARKER in html
    has_script = script_marker in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("보고서 presentation 주입 상태가 불완전하다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("보고서 presentation 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", script + "\n</body>", 1)


def inject_main_reporting(html: str) -> str:
    if '<div class="head-right">' not in html:
        raise DashboardBuildError("Main 보고서 버튼을 넣을 헤더를 찾지 못했다")
    return _inject(html, script=_MAIN_JS, script_marker=MAIN_SCRIPT_MARKER)


def inject_strategy_reporting(html: str) -> str:
    if '<header class="topbar">' not in html:
        raise DashboardBuildError("Strategy 보고서 버튼을 넣을 헤더를 찾지 못했다")
    return _inject(html, script=_STRATEGY_JS, script_marker=STRATEGY_SCRIPT_MARKER)
