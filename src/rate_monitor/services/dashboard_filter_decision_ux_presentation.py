# ruff: noqa: E501
"""Search/Strategy 선택계층과 Strategy 의사결정 상세 노출 후속 presentation.

표시·선택 UX만 보정한다. 금리값, source precedence, stable product identity,
ranking aggregation, inflow prediction 계수·수식은 변경하지 않는다.

- Search 상품군을 예금/적금 복수선택 체크박스로 바꾼다.
- Strategy 업권을 저축은행 / 상호금융 부모 체크박스 + 상호금융 하위 업권으로 묶는다.
- 수신예측은 예금 단독 계산 계약을 유지하되, 통합/적금 화면에서도 상세 UI를 숨기지 않는다.
  비예금 단독 상태에서는 수치 계산을 fail-closed 하고 예금 단독 전용임을 명시한다.
- 시장 위치 참고와 예측모형 상세는 최초 진입 시 펼친 상태로 둔다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="dashboard-filter-decision-ux-style"'
SCRIPT_MARKER = 'id="dashboard-filter-decision-ux-script"'


STYLE = r"""
<style id="dashboard-filter-decision-ux-style">
/* 체크박스가 많아져도 부모/자식과 선택 상태가 한눈에 보이도록 계층을 만든다. */
.search-family-checks{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.search-family-checks label,.strategy-sector-family-controls .sector-family-parent{display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:8px 12px;border:1px solid rgba(91,47,100,.16);border-radius:10px;background:#fff;color:#4d3c51;font-size:12.5px;font-weight:820;cursor:pointer;box-shadow:0 1px 0 rgba(255,255,255,.8) inset}
.search-family-checks label:has(input:checked),.strategy-sector-family-controls .sector-family-parent:has(input:checked){border-color:#5b2f64;background:#5b2f64;color:#fff;box-shadow:0 0 0 2px rgba(91,47,100,.10)}
.search-family-checks input,.strategy-sector-family-controls input{width:16px;height:16px;margin:0;accent-color:#d33a7c}
.product-family-group .product-savings-detail{margin:8px 0 0 14px;padding:9px 11px;border-left:3px solid rgba(211,58,124,.28);background:#fbf7fb}
.product-family-group .product-savings-detail .nested-head{color:#5c4b60;font-size:11.5px;font-weight:760}
.product-family-group .product-savings-detail .checks label{min-height:36px;padding:7px 10px;border:1px solid rgba(91,47,100,.11);border-radius:9px;background:#fff;color:#5d4e61;font-size:11.5px}
.product-family-group .product-savings-detail .checks label:has(input:checked){border-color:rgba(211,58,124,.28);background:#fff1f7;color:#8a315b;font-weight:760}
#conditions .group{border-color:rgba(91,47,100,.09)!important}
#conditions .group>.lbl{color:#493a4d!important;font-weight:820!important}
#conditions .checks label:has(input:checked){color:#4d2d58;font-weight:760}

/* 기존 mode button은 runtime compatibility용으로 유지하되 사용자에게는 부모 체크박스를 보인다. */
#market-scope>.mode-tabs{display:none!important}
.strategy-sector-family-controls{display:grid;grid-template-columns:minmax(150px,.58fr) minmax(0,1.42fr);gap:9px;grid-column:1/-1;align-items:start}
.strategy-sector-family-controls .sector-family-parent{width:100%;justify-content:flex-start;background:#fbf9fb;color:#4f3c53}
.strategy-sector-family-controls .sector-family-parent small{margin-left:auto;color:inherit;opacity:.72;font-size:10.5px;font-weight:720}
.strategy-mutual-family{display:grid;gap:6px}
.strategy-mutual-children{margin-left:18px;padding:7px 8px 7px 11px;border-left:3px solid rgba(91,47,100,.16);border-radius:0 9px 9px 0;background:rgba(91,47,100,.035)}
.strategy-mutual-children .sector-toggles{display:flex!important;justify-content:flex-start!important;gap:6px!important;flex-wrap:wrap!important}
.strategy-mutual-children .sector-toggle{min-height:36px!important;padding:7px 9px!important;border-color:rgba(91,47,100,.12)!important;background:#fff!important;color:#57475b!important;font-size:11.5px!important}
.strategy-mutual-children .sector-toggle:has(input:checked){border-color:rgba(211,58,124,.27)!important;background:#fff2f7!important;color:#8e345e!important;font-weight:780!important}
.strategy-mutual-children .sector-toggle small{font-size:9.5px!important;color:#786b7b!important}
.strategy-sector-family-controls input:focus-visible,.search-family-checks input:focus-visible{outline:2px solid rgba(91,47,100,.50);outline-offset:2px}

/* 상세는 보이되 예금 단독이 아닐 때 계산 자체는 fail-closed 한다. */
.rate-response-scope-lock{padding:13px;border:1px solid rgba(169,116,26,.20);border-radius:9px;background:#fff8e9;color:#6f531f;font-size:11.5px;line-height:1.55;text-align:left}

@media(max-width:760px){
  .strategy-sector-family-controls{grid-template-columns:1fr}
  .strategy-mutual-children{margin-left:12px}
  .search-family-checks label,.strategy-sector-family-controls .sector-family-parent{font-size:12px}
}
</style>
""".strip()


SCRIPT = r"""
<script id="dashboard-filter-decision-ux-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);

  function installStrategySectorHierarchy(){
    const scope=$("market-scope"),modes=scope?.querySelector(":scope > .mode-tabs"),sectors=$("sector-toggles");
    if(!scope||!modes||!sectors||scope.querySelector(".strategy-sector-family-controls"))return;

    const host=document.createElement("div");
    host.className="strategy-sector-family-controls";
    host.setAttribute("aria-label","비교 업권 선택");
    host.innerHTML='<label class="sector-family-parent"><input type="checkbox" data-sector-family-toggle="savings_bank"><span>저축은행</span></label><div class="strategy-mutual-family"><label class="sector-family-parent"><input type="checkbox" data-sector-family-toggle="mutual_finance"><span>상호금융</span><small id="mutual-family-count">세부업권</small></label><div class="strategy-mutual-children"></div></div>';
    modes.insertAdjacentElement("afterend",host);
    host.querySelector(".strategy-mutual-children").appendChild(sectors);

    const order={cu:0,nh_local:1,kfcc:2};
    [...sectors.querySelectorAll(".sector-toggle")]
      .sort((a,b)=>(order[a.querySelector("[data-sector]")?.dataset.sector]??99)-(order[b.querySelector("[data-sector]")?.dataset.sector]??99))
      .forEach(label=>sectors.appendChild(label));

    const familyInput=key=>host.querySelector(`[data-sector-family-toggle="${key}"]`);
    const activeMode=()=>modes.querySelector("[data-market-mode].active")?.dataset.marketMode||"savings_bank";
    const sync=()=>{
      const mode=activeMode(),savings=familyInput("savings_bank"),mutual=familyInput("mutual_finance");
      if(savings)savings.checked=mode==="savings_bank"||mode==="combined";
      if(mutual)mutual.checked=mode==="mutual_finance"||mode==="combined";
      const children=[...sectors.querySelectorAll("input[data-sector]")],available=children.filter(x=>!x.disabled),selected=available.filter(x=>x.checked);
      const count=$("mutual-family-count");if(count)count.textContent=`${selected.length}/${available.length||children.length} 선택`;
    };
    host.addEventListener("change",e=>{
      const input=e.target.closest?.("[data-sector-family-toggle]");if(!input)return;
      const savings=familyInput("savings_bank").checked,mutual=familyInput("mutual_finance").checked;
      if(!savings&&!mutual){input.checked=true;return}
      const mode=savings&&mutual?"combined":mutual?"mutual_finance":"savings_bank";
      modes.querySelector(`[data-market-mode="${mode}"]`)?.click();
      queueMicrotask(sync);
    });
    sectors.addEventListener("change",()=>queueMicrotask(sync));
    new MutationObserver(sync).observe(modes,{subtree:true,attributes:true,attributeFilter:["class"]});
    new MutationObserver(sync).observe(sectors,{subtree:true,attributes:true,attributeFilter:["checked","disabled"]});
    sync();
  }

  function openDecisionDetailsByDefault(){
    const simForm=$("sim-form"),panel=$("prediction-panel"),toggle=$("prediction-toggle");
    if(simForm&&!simForm.hidden&&panel&&toggle){
      panel.hidden=false;
      toggle.hidden=false;
      toggle.setAttribute("aria-expanded","true");
      toggle.textContent="예측엔진 닫기";
    }
    const modelDetail=document.querySelector(".workspace-model-detail");
    if(modelDetail)modelDetail.open=true;
    const modelEvidence=document.querySelector(".decision-model-evidence");
    if(modelEvidence)modelEvidence.open=true;
    const marketReference=document.querySelector(".market-position-reference");
    if(marketReference)marketReference.open=true;
  }

  function install(){
    installStrategySectorHierarchy();
    openDecisionDetailsByDefault();
    requestAnimationFrame(openDecisionDetailsByDefault);
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
""".strip()


def _replace_required(html: str, old: str, new: str, label: str, *, count: int = 1) -> str:
    if old not in html:
        raise DashboardBuildError(f"필터/금리결정 UX anchor를 찾지 못했다: {label}")
    return html.replace(old, new, count)


def _inject_search(html: str) -> str:
    rendered = html
    old_family = '''  const activeProductFamily = () => state.picked.type.has(PRODUCT_DEPOSIT_TYPE)\n    ? "deposit"\n    : (PRODUCT_SAVINGS_TYPES.some((type) => state.picked.type.has(type)) || emptySavingsSelected)\n      ? "savings" : "deposit";'''
    new_family = '''  const activeProductFamily = () => {\n    const deposit = state.picked.type.has(PRODUCT_DEPOSIT_TYPE);\n    const savings = PRODUCT_SAVINGS_TYPES.some((type) => state.picked.type.has(type)) || emptySavingsSelected;\n    return deposit && savings ? "combined" : deposit ? "deposit" : savings ? "savings" : "deposit";\n  };'''
    rendered = _replace_required(rendered, old_family, new_family, "Search combined family state")

    old_set = '''  const setProductFamily = (family) => {\n    state.picked.type.clear();\n    emptySavingsSelected = false;\n    if (family === "savings") PRODUCT_SAVINGS_TYPES.forEach((type) => state.picked.type.add(type));\n    else state.picked.type.add(PRODUCT_DEPOSIT_TYPE);\n  };'''
    new_set = '''  const setProductFamily = (family, enabled = true) => {\n    if (family === "deposit") {\n      if (enabled) state.picked.type.add(PRODUCT_DEPOSIT_TYPE);\n      else state.picked.type.delete(PRODUCT_DEPOSIT_TYPE);\n      return;\n    }\n    if (family !== "savings") return;\n    emptySavingsSelected = false;\n    if (enabled) {\n      if (!PRODUCT_SAVINGS_TYPES.some((type) => state.picked.type.has(type)))\n        PRODUCT_SAVINGS_TYPES.forEach((type) => state.picked.type.add(type));\n    } else PRODUCT_SAVINGS_TYPES.forEach((type) => state.picked.type.delete(type));\n  };'''
    rendered = _replace_required(rendered, old_set, new_set, "Search family toggle behavior")

    old_note = '''  const noteSavingsSelection = () => {\n    if (state.picked.type.has(PRODUCT_DEPOSIT_TYPE)) { emptySavingsSelected = false; return; }\n    emptySavingsSelected = !PRODUCT_SAVINGS_TYPES.some((type) => state.picked.type.has(type));\n  };'''
    new_note = '''  const noteSavingsSelection = () => {\n    const parent = document.querySelector('[data-product-family-toggle="savings"]');\n    emptySavingsSelected = Boolean(parent?.checked)\n      && !PRODUCT_SAVINGS_TYPES.some((type) => state.picked.type.has(type));\n  };'''
    rendered = _replace_required(rendered, old_note, new_note, "Search savings subtype state")

    old_label = '''  const productScopeLabel = () => {\n    if (activeProductFamily() === "deposit") return "예금";\n    const picked = PRODUCT_SAVINGS_TYPES.filter((type) => state.picked.type.has(type));\n    if (picked.length === 2) return "적금 전체";\n    if (picked[0] === "installment_savings") return "적금 · 정기적금";\n    if (picked[0] === "flexible_savings") return "적금 · 자유적금";\n    return "적금 · 선택 없음";\n  };'''
    new_label = '''  const productScopeLabel = () => {\n    const family = activeProductFamily();\n    if (family === "deposit") return "예금";\n    const picked = PRODUCT_SAVINGS_TYPES.filter((type) => state.picked.type.has(type));\n    if (family === "combined") {\n      if (picked.length === 2) return "예금 + 적금";\n      if (!picked.length) return "예금 + 적금(유형 미선택)";\n      return picked[0] === "installment_savings" ? "예금 + 정기적금" : "예금 + 자유적금";\n    }\n    if (picked.length === 2) return "적금 전체";\n    if (picked[0] === "installment_savings") return "적금 · 정기적금";\n    if (picked[0] === "flexible_savings") return "적금 · 자유적금";\n    return "적금 · 선택 없음";\n  };'''
    rendered = _replace_required(rendered, old_label, new_label, "Search combined scope label")

    rendered = _replace_required(
        rendered,
        '    const detail = family === "savings" ? `<div class="product-savings-detail">',
        '    const detail = family !== "deposit" ? `<div class="product-savings-detail">',
        "Search combined savings detail visibility",
    )
    old_ui = '    return `<div class="group product-family-group"><div class="lbl">상품군</div><div class="product-family-tabs" role="group" aria-label="상품군"><button type="button" data-product-family="deposit" aria-pressed="${family === "deposit"}">예금</button><button type="button" data-product-family="savings" aria-pressed="${family === "savings"}">적금</button></div>${detail}<div class="product-term-row"><div class="lbl">가입기간</div><div class="global-term-tabs" role="group" aria-label="가입기간">${terms}</div></div></div>`;'
    new_ui = '    return `<div class="group product-family-group"><div class="lbl">상품군 <span class="selected">${family === "combined" ? "2/2" : "1/2"} 선택</span></div><div class="search-family-checks" role="group" aria-label="상품군 복수 선택"><label><input type="checkbox" data-product-family-toggle="deposit" ${family !== "savings" ? "checked" : ""}>예금</label><label><input type="checkbox" data-product-family-toggle="savings" ${family !== "deposit" ? "checked" : ""}>적금</label></div>${detail}<div class="product-term-row"><div class="lbl">가입기간</div><div class="global-term-tabs" role="group" aria-label="가입기간">${terms}</div></div></div>`;'
    rendered = _replace_required(rendered, old_ui, new_ui, "Search family checkbox markup")

    old_event = '''    const family = e.target.closest("[data-product-family]");\n    if (family) { setProductFamily(family.dataset.productFamily); renderGroups(); renderPresets(); redraw(); return; }'''
    new_event = '''    const family = e.target.closest("input[data-product-family-toggle]");\n    if (family) {\n      const peer = document.querySelector(`input[data-product-family-toggle=\"${family.dataset.productFamilyToggle === "deposit" ? "savings" : "deposit"}\"]`);\n      if (!family.checked && !peer?.checked) { family.checked = true; return; }\n      setProductFamily(family.dataset.productFamilyToggle, family.checked);\n      renderGroups(); renderPresets(); redraw(); return;\n    }'''
    rendered = _replace_required(rendered, old_event, new_event, "Search family checkbox event")

    rendered = _replace_required(
        rendered,
        '} else if (family === "savings") {\n      const selected = rawSavings === null',
        '} else if (family === "savings" || family === "combined") {\n      const selected = rawSavings === null',
        "Search combined alias normalization",
    )
    rendered = _replace_required(
        rendered,
        '      const encoded = selected.join(",");',
        '      const encoded = (family === "combined" ? [PRODUCT_DEPOSIT_TYPE, ...selected] : selected).join(",");',
        "Search combined alias encoded types",
    )
    rendered = _replace_required(
        rendered,
        '    if (p.get("family") === "savings") {',
        '    if (p.get("family") === "savings" || p.get("family") === "combined") {',
        "Search combined alias restore",
    )
    rendered = _replace_required(
        rendered,
        '    if (family === "savings") {\n      const selected = PRODUCT_SAVINGS_TYPES.filter((type) => state.picked.type.has(type));',
        '    if (family !== "deposit") {\n      const selected = PRODUCT_SAVINGS_TYPES.filter((type) => state.picked.type.has(type));',
        "Search combined URL decoration",
    )
    return rendered


def _inject_strategy(html: str) -> str:
    rendered = html
    # product-scope layer가 boot 때 예측 패널을 무조건 닫던 회귀를 제거한다.
    rendered = _replace_required(
        rendered,
        '$("prediction-toggle").hidden=installmentMode;$("prediction-panel").hidden=true;',
        '$("prediction-toggle").hidden=mutualOnly;$("prediction-panel").hidden=mutualOnly;',
        "Strategy default prediction disclosure",
    )
    # combined 후속 layer도 패널 자체는 숨기지 않는다. 계산 가드는 그대로 유지한다.
    rendered = _replace_required(
        rendered,
        'if(toggle)toggle.hidden=true;if(panel)panel.hidden=true;',
        'if(toggle)toggle.hidden=false;if(panel)panel.hidden=false;',
        "Strategy combined prediction details visibility",
    )

    # Cockpit의 별도 시나리오 표가 combined 시장 TOP10을 예금 예측에 섞지 않게 fail-closed 한다.
    rendered = _replace_required(
        rendered,
        '    const host=$("rate-response-body");\n    if(!host)return;\n    const baseline=inputNum("baseline-new")',
        '    const host=$("rate-response-body");\n    if(!host)return;\n    const depositOnly=document.querySelector(\'[data-product-family-toggle="deposit"]\')?.checked&&!document.querySelector(\'[data-product-family-toggle="savings"]\')?.checked;\n    if(!depositOnly){host.innerHTML=\'<div class="rate-response-scope-lock">수신금액 예측 계산은 예금 단독 전용입니다. 현재 비교 범위와 별개로 세부 구조는 확인할 수 있으며, 예금만 선택하면 금리별 수신반응 계산이 활성화됩니다.</div>\';return;}\n    const baseline=inputNum("baseline-new")',
        "Cockpit deposit-only scenario guard",
    )
    # 세부 민감도 카드 역시 같은 예금 단독 경계를 적용한다.
    rendered = _replace_required(
        rendered,
        '  function renderSensitivity(){const host=$("decision-sensitivity-grid"),config=model();if(!host||!config)return;const baseline=input("baseline-new")',
        '  function renderSensitivity(){const host=$("decision-sensitivity-grid"),config=model();if(!host||!config)return;const depositOnly=document.querySelector(\'[data-product-family-toggle="deposit"]\')?.checked&&!document.querySelector(\'[data-product-family-toggle="savings"]\')?.checked;if(!depositOnly){host.innerHTML=\'<div class="decision-sensitivity-empty" style="grid-column:1/-1">수신예측 민감도 계산은 예금 단독 전용입니다. 예금만 선택하면 저·기준·고민감 결과가 활성화됩니다.</div>\';return}const baseline=input("baseline-new")',
        "Sensitivity deposit-only guard",
    )

    if "</head>" not in rendered or "</body>" not in rendered:
        raise DashboardBuildError("Strategy 필터/금리결정 UX 주입 위치를 찾지 못했다")
    rendered = rendered.replace("</head>", STYLE + "\n</head>", 1)
    return rendered.replace("</body>", SCRIPT + "\n</body>", 1)


def inject_dashboard_filter_decision_ux(html: str) -> str:
    """Search 복수 상품군과 Strategy 업권계층/상세 기본노출을 적용한다."""
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        return html
    if 'id="market-scope"' in html and 'id="prediction-panel"' in html:
        return _inject_strategy(html)
    if 'id="conditions"' in html and "activeProductFamily" in html:
        rendered = _inject_search(html)
        if "</head>" not in rendered:
            raise DashboardBuildError("Search 필터 UX style 주입 위치를 찾지 못했다")
        return rendered.replace("</head>", STYLE + "\n</head>", 1)
    return html
