"""전략 대시보드의 후행 UI refinement.

수신 예측 계산식이나 canonical market universe는 건드리지 않고, 이미 적용된
전략 template contract 위에 표시 방식만 보강한다. 큰 원본 HTML을 직접 수정하지
않고 marker 기반으로 실패를 명시적으로 드러낸다.
"""

from rate_monitor.services.dashboard_service import DashboardBuildError


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise DashboardBuildError(
            f"전략 refinement marker를 찾지 못했다: {label} ({text.count(old)}건)"
        )
    return text.replace(old, new, 1)


def _adapt_prediction_panel(text: str) -> str:
    """예측엔진을 명시적 버튼으로 열고, 쉬운 설명과 근거 주석을 붙인다."""
    text = _replace_once(
        text,
        '<span class="chip">PREDICT v1</span>',
        '<button class="engine-toggle" id="prediction-toggle" type="button" '
        'aria-expanded="false" aria-controls="prediction-panel">예측엔진 보기</button>',
        "prediction.toggle",
    )

    panel_intro = (
        '<div id="prediction-panel" class="prediction-panel" hidden>'
        '<div class="prediction-explain"><b>쉽게 보면</b><p>'
        '최근 신규수신액을 출발점으로 잡고, 다음 만기자금 중 다시 남을 금액을 '
        '별도로 계산한 뒤, 제안금리가 현재보다 얼마나 높거나 낮은지에 따라 두 값을 '
        '조정해 합칩니다. 그래서 새로 들어오는 돈과 만기 후 남는 돈을 섞지 않습니다.'
        '</p></div>\n      '
    )
    text = _replace_once(
        text,
        '<div class="prediction-head"><b>수신금액 예측 엔진</b>',
        panel_intro + '<div class="prediction-head"><b>수신금액 예측 엔진</b>',
        "prediction.panel_open",
    )

    old_detail_warning = (
        '<p class="model-detail" id="inflow-model-detail">당사 현재금리와 시장 상위10%선을 '
        '확인한 뒤 계산합니다.</p>\n      '
        '<p class="warning">예측엔진 v1은 내부 수신실적 계수가 아직 미보정된 구조모형입니다. '
        '표시 범위는 민감도 스트레스 결과이며 실제 유입을 보장하지 않습니다.</p>'
    )
    new_detail_warning = (
        '<p class="model-detail" id="inflow-model-detail">당사 현재금리와 시장 상위10%선을 '
        '확인한 뒤 계산합니다.</p>\n      '
        '<div class="model-evidence"><b>모형 근거 · 어떤 부분을 어디서 가져왔나</b>'
        '<span><strong>상대금리 → 수신 선택</strong> · 자기 은행 예금금리가 시장 평균보다 '
        '높거나 낮을 때 시장점유율이 움직이는 구조는 Federal Reserve FEDS의 예금수요 '
        '모형을 참고했습니다. <a href="https://www.federalreserve.gov/pubs/feds/'
        '2013/201380/index.html" target="_blank" rel="noopener noreferrer">'
        'Fed FEDS 2013 · Sticky Deposit Rates</a></span>'
        '<span><strong>금리 변화 → 예금 flow 민감도</strong> · 은행이 예금금리를 올릴 때 '
        '예금 flow가 얼마나 반응하는지 추정하고, 그 민감도가 시기별로 크게 달라진다는 '
        'NY Fed 연구를 근거로 단일값 대신 범위를 둡니다. '
        '<a href="https://libertystreeteconomics.newyorkfed.org/2025/07/'
        'the-rise-in-deposit-flightiness-and-its-implications-for-financial-stability/" '
        'target="_blank" rel="noopener noreferrer">NY Fed 2025 · Deposit Flightiness</a></span>'
        '<span><strong>국내 비은행 수신경쟁</strong> · 한국은행은 은행권 수신경쟁에 대응해 '
        '저축은행 등 비은행권이 예금금리를 빠르게 올리고 수신이 이동한 사례를 분석했습니다. '
        '<a href="https://www.bok.or.kr/portal/bbs/P0002353/view.do?'
        'menuNo=200433&amp;nttId=10081072" target="_blank" rel="noopener noreferrer">'
        '한국은행 BOK 이슈노트 2023-33</a></span>'
        '<span><strong>exp / logistic 함수</strong> · 신규자금은 음수가 되지 않게 log-link '
        '형태를, 재예치율은 0~100% 확률 범위를 지키도록 logistic link를 쓴 통계적 '
        '모형 선택입니다. 특정 은행의 검증계수를 가져온 부분은 아닙니다.</span>'
        '<span class="assumption-source"><strong>β·γ 민감도 숫자</strong> · 현재 저·기준·고 '
        '계수는 외부 논문값이나 고려저축은행 실적 추정치가 아니라 내부 실적 미보정 '
        '스트레스 가정입니다. 실제 실적을 확보하면 재추정해야 합니다.</span></div>\n      '
        '<p class="warning"><strong>공신력 범위:</strong> 이 엔진은 Fed·한국은행의 공식 '
        '예측식을 그대로 복제한 것이 아니라, 연구에서 확인된 경제적 관계와 표준 통계 '
        'link를 조합한 내부 구조모형입니다. 현재 민감도 계수는 미보정이며 실제 유입을 '
        '보장하지 않습니다.</p></div>'
    )
    text = _replace_once(
        text,
        old_detail_warning,
        new_detail_warning,
        "prediction.evidence",
    )

    helper = (
        'function togglePredictionPanel(){'
        'const panel=$("prediction-panel"),button=$("prediction-toggle"),'
        'opening=panel.hidden;panel.hidden=!opening;'
        'button.setAttribute("aria-expanded",opening?"true":"false");'
        'button.textContent=opening?"예측엔진 닫기":"예측엔진 보기"}\n'
    )
    text = _replace_once(
        text,
        'function predictionNumber(id,{min=0,max=Infinity}={}){',
        helper + 'function predictionNumber(id,{min=0,max=Infinity}={}){',
        "prediction.toggle_helper",
    )
    text = _replace_once(
        text,
        '["baseline-new","maturity-amount","rollover-rate"].forEach('
        'id=>$(id).addEventListener("input",updateSim));',
        '["baseline-new","maturity-amount","rollover-rate"].forEach('
        'id=>$(id).addEventListener("input",updateSim));'
        '$("prediction-toggle").addEventListener("click",togglePredictionPanel);',
        "prediction.toggle_listener",
    )
    return text


def _adapt_national_map_readability(text: str) -> str:
    """전국 카드 비율과 시도 라벨 위치만 보정한다. 데이터 좌표는 유지한다."""
    css = (
        '@media(min-width:1121px){'
        '.primary:not(.busan-focus){grid-template-columns:minmax(470px,.86fr) '
        'minmax(590px,1.14fr)}'
        '.primary:not(.busan-focus) .tablewrap table{min-width:540px}'
        '}'
        '.primary:not(.busan-focus) .node-label{font-size:14px;paint-order:stroke;'
        'stroke:#081511;stroke-width:3px;stroke-linejoin:round}'
        '.primary:not(.busan-focus) .node-rate{font-size:15px;paint-order:stroke;'
        'stroke:#081511;stroke-width:3px;stroke-linejoin:round}'
        '.primary:not(.busan-focus) .node-line{stroke:rgba(128,200,166,.32);'
        'stroke-width:1.2}'
        '.engine-toggle{border:1px solid rgba(128,200,166,.28);border-radius:9px;'
        'background:rgba(73,125,97,.14);color:#cfe6d9;padding:6px 9px;font-size:8.8px;'
        'font-weight:760;cursor:pointer;white-space:nowrap}'
        '.engine-toggle:hover,.engine-toggle:focus-visible{'
        'border-color:rgba(128,200,166,.52);background:rgba(73,125,97,.24);outline:none}'
        '.prediction-panel{display:grid;gap:10px;padding:11px;border:1px solid var(--line);'
        'border-radius:12px;background:rgba(5,17,13,.24)}'
        '.prediction-panel[hidden]{display:none}'
        '.prediction-explain{padding:10px 11px;border-radius:10px;'
        'background:rgba(128,200,166,.07);border:1px solid rgba(128,200,166,.12)}'
        '.prediction-explain b{display:block;color:#d9e8e0;font-size:10px}'
        '.prediction-explain p{margin:4px 0 0;color:#82938a;font-size:9px;line-height:1.6}'
        '.model-evidence{display:grid;gap:7px;padding:10px 11px;border:1px solid var(--line);'
        'border-radius:10px;background:rgba(4,14,11,.2)}'
        '.model-evidence>b{color:#d7e0db;font-size:9.5px}'
        '.model-evidence span{display:block;color:#74867d;font-size:8.5px;line-height:1.55}'
        '.model-evidence strong{color:#a8bbb1}'
        '.model-evidence a{color:#9ccdb8;text-decoration:none;'
        'border-bottom:1px solid rgba(156,205,184,.25)}'
        '.model-evidence .assumption-source{color:#b8a579}'
    )
    text = _replace_once(text, "</style>", css + "</style>", "national_map.css")

    label_offsets = (
        'const koreaLabelOffsets={"서울":[-28,-24,"end"],"인천":[-30,4,"end"],'
        '"경기":[28,-2,"start"],"강원":[28,-12,"start"],"충북":[30,-12,"start"],'
        '"충남":[-32,-12,"end"],"세종":[-18,18,"end"],"대전":[-30,10,"end"],'
        '"경북":[30,-8,"start"],"대구":[28,6,"start"],"울산":[28,-4,"start"],'
        '"부산":[30,10,"start"],"경남":[-34,12,"end"],"전북":[-32,-6,"end"],'
        '"광주":[-34,4,"end"],"전남":[-34,18,"end"],"제주":[30,0,"start"]};\n'
    )
    text = _replace_once(
        text,
        "// 부산 경계:",
        label_offsets + "// 부산 경계:",
        "national_map.label_offsets",
    )

    old_nodes = (
        '  $("nodes").innerHTML=a.map(x=>{'
        'const[cx,cy]=coords[x.region],right=cx>400,'
        'lx=right?cx-22:cx+22,anchor=right?"end":"start",'
        'klass=["node",x.region===top?"top":"",'
        'x.region==="부산"?"busan clickable":""].filter(Boolean).join(" ");'
        'return`<g class="${klass}" data-region="${esc(x.region)}" '
        'role="${x.region==="부산"?"button":"img"}" '
        'tabindex="${x.region==="부산"?"0":"-1"}" '
        'aria-label="${esc(x.region)} 지역 평균 ${x.rate.toFixed(2)}%'
        '${x.region==="부산"?", 부산 지도 확대":""}">'
        '<line class="node-line" x1="${cx}" y1="${cy}" '
        'x2="${right?cx-34:cx+34}" y2="${cy-11}"/>'
        '<circle class="node-ring" cx="${cx}" cy="${cy}" '
        'r="${x.region===top?14:11}"/>'
        '<circle class="node-core" cx="${cx}" cy="${cy}" r="4.3"/>'
        '<text class="node-label" x="${lx}" y="${cy-16}" '
        'text-anchor="${anchor}">${esc(x.region)}</text>'
        '<text class="node-rate" x="${lx}" y="${cy-3}" '
        'text-anchor="${anchor}">${x.rate.toFixed(2)}%</text>'
        '</g>`}).join("");'
    )
    new_nodes = (
        '  $("nodes").innerHTML=a.map(x=>{'
        'const[cx,cy]=coords[x.region],preset=koreaLabelOffsets[x.region]'
        '||[22,-16,"start"],dx=preset[0],dy=preset[1],anchor=preset[2],'
        'lx=cx+dx,labelY=cy+dy,rateY=labelY+14,'
        'lineX=anchor==="end"?lx+7:anchor==="start"?lx-7:lx,lineY=labelY+5,'
        'klass=["node",x.region===top?"top":"",'
        'x.region==="부산"?"busan clickable":""].filter(Boolean).join(" ");'
        'return`<g class="${klass}" data-region="${esc(x.region)}" '
        'role="${x.region==="부산"?"button":"img"}" '
        'tabindex="${x.region==="부산"?"0":"-1"}" '
        'aria-label="${esc(x.region)} 지역 평균 ${x.rate.toFixed(2)}%'
        '${x.region==="부산"?", 부산 지도 확대":""}">'
        '<line class="node-line" x1="${cx}" y1="${cy}" '
        'x2="${lineX}" y2="${lineY}"/>'
        '<circle class="node-ring" cx="${cx}" cy="${cy}" '
        'r="${x.region===top?14:11}"/>'
        '<circle class="node-core" cx="${cx}" cy="${cy}" r="4.3"/>'
        '<text class="node-label" x="${lx}" y="${labelY}" '
        'text-anchor="${anchor}">${esc(x.region)}</text>'
        '<text class="node-rate" x="${lx}" y="${rateY}" '
        'text-anchor="${anchor}">${x.rate.toFixed(2)}%</text>'
        '</g>`}).join("");'
    )
    return _replace_once(
        text,
        old_nodes,
        new_nodes,
        "national_map.node_labels",
    )


def adapt_strategy_refinements(text: str) -> str:
    """예측엔진 노출 방식과 전국 지도 가독성을 후행 보정한다."""
    return _adapt_national_map_readability(_adapt_prediction_panel(text))
