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


def _take_between(
    text: str,
    start_marker: str,
    end_marker: str,
    label: str,
) -> tuple[str, str]:
    if text.count(start_marker) != 1:
        raise DashboardBuildError(
            f"전략 refinement 시작 marker를 찾지 못했다: {label} "
            f"({text.count(start_marker)}건)"
        )
    start = text.index(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if end == -1:
        raise DashboardBuildError(f"전략 refinement 종료 marker를 찾지 못했다: {label}")
    segment = text[start:end]
    return text[:start] + text[end:], segment


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
        'link를 조합한 내부 구조모형입니다. 내부 수신실적 계수가 아직 미보정되어 '
        '표시 범위는 민감도 스트레스 결과이며 실제 유입을 보장하지 않습니다.</p></div>'
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


def _adapt_information_flow(text: str) -> str:
    """시장 흐름 → 경쟁 구조 → 해석 → 상품 기획 순으로 DOM을 재배치한다."""
    text, chart = _take_between(
        text,
        '<section class="card pad chartcard">',
        '<details class="card changes">',
        "layout.rate_trend",
    )
    text, changes = _take_between(
        text,
        '<details class="card changes">',
        '<footer class="foot">',
        "layout.market_changes",
    )
    text, preference = _take_between(
        text,
        '  <article class="card pad">\n'
        '    <div class="head"><div><h2>우대조건 트렌드',
        '  <article class="card sim">',
        "layout.preference",
    )
    text, simulator = _take_between(
        text,
        '  <article class="card sim">',
        '  <article class="card pad insightcard">',
        "layout.simulator",
    )

    changes = _replace_once(
        changes,
        '<details class="card changes">',
        '<details class="card changes" open>',
        "layout.market_changes_open",
    )
    preference = _replace_once(
        preference,
        '<article class="card pad">',
        '<article class="card pad preference-card">',
        "layout.preference_class",
    )
    text = _replace_once(
        text,
        '<section class="grid analytics">',
        '<section class="grid interpretation" aria-label="시장 해석과 우대조건">',
        "layout.interpretation",
    )

    market_flow = (
        '<section class="grid market-flow" aria-label="시장 금리와 최근 변화 흐름">\n'
        + chart.rstrip()
        + "\n"
        + changes.rstrip()
        + "\n</section>\n"
    )
    text = _replace_once(
        text,
        '</section>\n<section class="grid primary">',
        '</section>\n' + market_flow + '<section class="grid primary">',
        "layout.market_flow_position",
    )

    planning = (
        preference.rstrip()
        + "\n</section>\n"
        + '<section class="planning-zone" aria-label="신상품 기획">\n'
        + simulator.rstrip()
        + "\n</section>\n"
    )
    text = _replace_once(
        text,
        '</section>\n<footer class="foot">',
        planning + '<footer class="foot">',
        "layout.planning_position",
    )

    trend_summary = (
        '<div class="trend-summary" aria-label="금리 흐름 요약">'
        '<div><span>시장 평균 변화</span><b id="trend-mean-change">—</b>'
        '<small id="trend-mean-note">이력 확인 중</small></div>'
        '<div><span>시장 최고 변화</span><b id="trend-max-change">—</b>'
        '<small id="trend-max-note">이력 확인 중</small></div>'
        '<div><span>고려저축은행 변화</span><b id="trend-own-change">—</b>'
        '<small id="trend-own-note">이력 확인 중</small></div>'
        '<div><span>현재 상단 프리미엄</span><b id="trend-premium">—</b>'
        '<small>시장 최고 - 시장 평균</small></div></div>'
    )
    text = _replace_once(
        text,
        '<div class="chartwrap">',
        trend_summary + '<div class="chartwrap">',
        "layout.trend_summary",
    )

    change_direction = (
        '<div class="change-direction">'
        '<div class="change-direction-head"><span>30일 변화 방향</span>'
        '<b id="change-direction-copy">계산 중</b></div>'
        '<div class="change-balance" aria-label="상승·하락 이벤트 비중">'
        '<i class="up" id="change-up-bar"></i>'
        '<i class="down" id="change-down-bar"></i></div>'
        '<div class="change-direction-foot"><span id="change-up-share">상승 —</span>'
        '<span id="change-down-share">하락 —</span></div>'
        '<small id="change-direction-note">상품 이벤트 방향을 계산합니다.</small></div>'
    )
    text = _replace_once(
        text,
        '<p class="note">동일 상품 variant 동시 변경은 상품 이벤트 1건으로 집계합니다.',
        change_direction
        + '<p class="note">동일 상품 variant 동시 변경은 상품 이벤트 1건으로 집계합니다.',
        "layout.change_direction",
    )

    planning_strip = (
        '<div class="planning-strip" aria-label="현재 시장 기획 기준">'
        '<div><span>30일 시장 방향</span><b id="plan-flow">—</b>'
        '<small id="plan-flow-note">변화 확인 중</small></div>'
        '<div><span>선택기간 시장 최고</span><b id="plan-market-max">—</b>'
        '<small id="plan-market-max-note">비교군 확인 중</small></div>'
        '<div><span>선택기간 시장 평균</span><b id="plan-market-mean">—</b>'
        '<small id="plan-market-mean-note">비교군 확인 중</small></div>'
        '<div><span>상위 10% 진입선</span><b id="plan-top10">—</b>'
        '<small id="plan-top10-note">비교군 확인 중</small></div>'
        '<div><span>고려저축은행 현재</span><b id="plan-own">—</b>'
        '<small id="plan-own-note">당사 상품 확인 중</small></div></div>'
    )
    text = _replace_once(
        text,
        '<div class="simform">',
        planning_strip + '<div class="simform">',
        "layout.planning_strip",
    )
    text = _replace_once(
        text,
        "금리를 정하면 실제 시장 포지션과 수신금액 구조모형을 함께 계산합니다.",
        "시장 흐름을 확인한 뒤 금리·우대·기간을 설계하고 시장 위치와 수신 시나리오를 "
        "함께 비교합니다.",
        "layout.simulator_copy",
    )
    text = _replace_once(
        text,
        "현재 canonical 데이터와 변경이력에서 자동 계산한 신호",
        "금리·경쟁강도·당사 위치·지역·우대조건을 묶어 신상품 기획 관점으로 해석",
        "layout.insight_copy",
    )
    text = _replace_once(
        text,
        "최근 시장 변화 · 최근 30일 상세 이벤트",
        "최근 시장 변화 · 30일 방향과 주요 이벤트",
        "layout.change_copy",
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


def _adapt_dashboard_flow_css(text: str) -> str:
    """새 정보 흐름의 크기와 그리드를 후행 override로 고정한다."""
    css = (
        '.market-flow{grid-template-columns:minmax(0,1.58fr) minmax(330px,.62fr);'
        'margin-bottom:12px;align-items:stretch}'
        '.market-flow .chartcard,.market-flow .changes{margin-bottom:0;min-height:420px}'
        '.market-flow .chartwrap{height:235px}'
        '.trend-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));'
        'gap:7px;margin:0 0 10px}'
        '.trend-summary>div{padding:9px 10px;border:1px solid var(--line);border-radius:9px;'
        'background:rgba(4,14,11,.24)}'
        '.trend-summary span{display:block;color:#687a71;font-size:8.4px}'
        '.trend-summary b{display:block;margin-top:2px;color:#dce5e0;font:770 13px var(--mono)}'
        '.trend-summary small{display:block;margin-top:2px;color:#5f7168;font-size:7.7px}'
        '.market-flow .changes summary{padding:15px 16px 12px}'
        '.market-flow .changes-body{padding:0 15px 14px}'
        '.market-flow .changestats{grid-template-columns:1fr 1fr}'
        '.market-flow .feed{grid-template-columns:1fr;max-height:190px;overflow:auto;'
        'padding-right:2px}'
        '.change-direction{margin:9px 0;padding:10px;border:1px solid var(--line);'
        'border-radius:9px;background:rgba(4,14,11,.22)}'
        '.change-direction-head,.change-direction-foot{display:flex;justify-content:space-between;'
        'gap:8px;align-items:center}'
        '.change-direction-head span{color:#71827a;font-size:8.6px}'
        '.change-direction-head b{color:#d9e2dd;font-size:9px}'
        '.change-balance{display:flex;height:7px;margin:8px 0 6px;border-radius:99px;'
        'overflow:hidden;background:#172620}'
        '.change-balance i.up{background:#b96565}.change-balance i.down{background:#4c9f7b}'
        '.change-direction-foot{color:#71827a;font-size:8px}'
        '.change-direction>small{display:block;margin-top:5px;color:#596c63;font-size:7.7px}'
        '.interpretation{grid-template-columns:minmax(0,1.45fr) minmax(320px,.55fr);'
        'margin-bottom:12px;align-items:stretch}'
        '.interpretation .insightcard,.interpretation .preference-card{min-height:330px}'
        '.interpretation .insights{grid-template-columns:1fr 1fr}'
        '.interpretation .insight:last-child{grid-column:1/-1}'
        '.insight em{display:block;color:#789087;font-size:7.8px;font-style:normal;'
        'font-weight:760;letter-spacing:.04em}'
        '.insight small{display:block;margin-top:5px;color:#879a90;font-size:8.2px;'
        'line-height:1.45}'
        '.planning-zone{margin-bottom:12px}'
        '.planning-zone .sim{padding:22px}'
        '.planning-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));'
        'gap:8px;margin-bottom:14px}'
        '.planning-strip>div{padding:10px 11px;border:1px solid var(--line);border-radius:10px;'
        'background:rgba(4,14,11,.28)}'
        '.planning-strip span{display:block;color:#6d7e76;font-size:8.5px}'
        '.planning-strip b{display:block;margin-top:3px;color:#dde7e1;font:780 15px var(--mono)}'
        '.planning-strip small{display:block;margin-top:2px;color:#5f7168;font-size:7.8px}'
        '@media(min-width:980px){'
        '.planning-zone .simform{grid-template-columns:minmax(320px,.78fr) minmax(0,1.22fr);'
        'column-gap:16px;align-items:start}'
        '.planning-zone .simrow,.planning-zone .choice-box{grid-column:1}'
        '.planning-zone .simresults{grid-column:2;grid-row:1/3;'
        'grid-template-columns:1fr 1fr}'
        '.planning-zone .position{grid-column:2;grid-row:3}'
        '.planning-zone .prediction-panel{grid-column:1/-1}'
        '}'
        '@media(min-width:1121px){'
        '.primary:not(.busan-focus) .mapcard{min-height:510px}'
        '.primary:not(.busan-focus) .mapstage{height:420px}'
        '.primary:not(.busan-focus)>article:last-child{min-height:510px}'
        '.primary:not(.busan-focus) td{padding:9px 8px}'
        '}'
        '@media(max-width:1120px){'
        '.market-flow,.interpretation{grid-template-columns:1fr}'
        '.market-flow .chartcard,.market-flow .changes{min-height:0}'
        '.interpretation .insightcard,.interpretation .preference-card{min-height:0}'
        '}'
        '@media(max-width:760px){'
        '.trend-summary,.planning-strip{grid-template-columns:1fr 1fr}'
        '.interpretation .insights{grid-template-columns:1fr}'
        '.interpretation .insight:last-child{grid-column:auto}'
        '}'
        '@media(max-width:480px){.trend-summary,.planning-strip{grid-template-columns:1fr}}'
    )
    return _replace_once(text, "</style>", css + "</style>", "layout.css")


def _adapt_dashboard_flow_behavior(text: str) -> str:
    """기존 데이터만으로 흐름 요약·인사이트·기획 context를 강화한다."""
    behavior = """
function formatBp(delta){
  if(!Number.isFinite(delta))return "—";
  const bp=delta*100,abs=Math.abs(bp),digits=abs>=10?0:1;
  return `${bp>=0?"+":""}${bp.toFixed(digits)}bp`;
}
function marketDirection(c){
  const up=Number(c.up_count||0),down=Number(c.down_count||0),total=up+down;
  if(!total)return{label:"변화 없음",up,down,total,upShare:0,downShare:0};
  const upShare=up/total*100,downShare=down/total*100;
  const label=up>down?"상승 우세":down>up?"하락 우세":"혼조";
  return{label,up,down,total,upShare,downShare};
}
function renderTrendEnhanced(){
  const tr=data.strategy?.rate_trend||{};
  const pts=(tr.points||[]).filter(x=>
    Number.isFinite(Number(x.mean_max_rate))&&Number.isFinite(Number(x.market_max_rate))
  );
  $("trend-window").textContent=`최근 ${tr.window_days||63}일`;
  const grid=$("trend-grid"),series=$("trend-series");
  if(!pts.length){
    grid.innerHTML="";
    series.innerHTML='<text x="500" y="140" text-anchor="middle" class="axistext">'
      +'기간별 이력 데이터가 없습니다.</text>';
    $("trend-note").textContent="정상 수집일 snapshot이 쌓이면 시장·우리회사 추이를 표시합니다.";
    $("trend-delta").textContent="이력 없음";
    ["trend-mean-change","trend-max-change","trend-own-change","trend-premium"]
      .forEach(id=>$(id).textContent="—");
    return;
  }
  const fields=["mean_max_rate","market_max_rate","our_company_max_rate"];
  const vals=pts.flatMap(p=>fields.map(f=>Number(p[f])).filter(Number.isFinite));
  const lo=Math.min(...vals),hi=Math.max(...vals),pad=Math.max(.04,(hi-lo)*.16);
  const min=Math.max(0,lo-pad),max=hi+pad,x0=72,x1=970,y0=22,y1=230;
  const sx=i=>pts.length===1?(x0+x1)/2:x0+(x1-x0)*i/(pts.length-1);
  const sy=v=>y1-(v-min)/(max-min)*(y1-y0);
  grid.innerHTML=[0,.25,.5,.75,1].map(q=>{
    const y=y0+(y1-y0)*q,v=max-(max-min)*q;
    return `<line class="gridline" x1="${x0}" y1="${y}" x2="${x1}" y2="${y}"/>`
      +`<text class="axistext" x="10" y="${y+3}">${v.toFixed(2)}%</text>`;
  }).join("");
  const build=(field,klass,withFill=false)=>{
    const points=pts.map((p,i)=>({
      x:sx(i),y:Number.isFinite(Number(p[field]))?sy(Number(p[field])):null,
      value:Number(p[field])
    })).filter(p=>p.y!==null);
    const path=points.map((p,i)=>`${i?"L":"M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
      .join(" ");
    if(!points.length)return"";
    let html=withFill
      ?`<path class="trendfill" d="${path} L${points.at(-1).x},${y1} `
        +`L${points[0].x},${y1} Z"/>`
      :"";
    html+=`<path class="trendline ${klass}" d="${path}"/>`;
    html+=points.map(p=>
      `<circle class="trenddot ${klass}" cx="${p.x}" cy="${p.y}" r="3.5"/>`
    ).join("");
    const last=points.at(-1),labelY=klass==="own"
      ?Math.min(y1-4,last.y+15):Math.max(12,last.y-10);
    html+=`<text class="trendlabel ${klass}" x="${last.x}" y="${labelY}" `
      +`text-anchor="end">${last.value.toFixed(2)}%</text>`;
    return html;
  };
  series.innerHTML=build("mean_max_rate","mean",true)
    +build("market_max_rate","max")+build("our_company_max_rate","own")
    +pts.map((p,i)=>{
      const d=new Date(`${p.date}T00:00:00`);
      const label=Number.isNaN(d.getTime())?p.date
        :`${String(d.getMonth()+1).padStart(2,"0")}/${String(d.getDate()).padStart(2,"0")}`;
      return `<text class="trenddate" x="${sx(i)}" y="257" `
        +`text-anchor="middle">${label}</text>`;
    }).join("");
  const first=pts[0],last=pts.at(-1);
  const meanDelta=Number(last.mean_max_rate)-Number(first.mean_max_rate);
  const maxDelta=Number(last.market_max_rate)-Number(first.market_max_rate);
  const ownPts=pts.filter(x=>Number.isFinite(Number(x.our_company_max_rate)));
  const ownDelta=ownPts.length>1
    ?Number(ownPts.at(-1).our_company_max_rate)-Number(ownPts[0].our_company_max_rate)
    :null;
  const premium=Number(last.market_max_rate)-Number(last.mean_max_rate);
  $("trend-mean-change").textContent=formatBp(meanDelta);
  $("trend-max-change").textContent=formatBp(maxDelta);
  $("trend-own-change").textContent=Number.isFinite(ownDelta)?formatBp(ownDelta):"관측 부족";
  $("trend-premium").textContent=formatBp(premium);
  $("trend-mean-note").textContent=`${first.date} → ${last.date}`;
  $("trend-max-note").textContent=`현재 ${Number(last.market_max_rate).toFixed(2)}%`;
  $("trend-own-note").textContent=ownPts.length
    ?`현재 ${Number(ownPts.at(-1).our_company_max_rate).toFixed(2)}% · ${ownPts.length}회 관측`
    :"당사 관측 없음";
  $("trend-delta").textContent=`평균 ${meanDelta>=0?"+":""}${meanDelta.toFixed(2)}%p`;
  $("trend-note").textContent=`${pts.length}개 정상 수집일 snapshot · 현재 시장 최고-평균 `
    +`${premium.toFixed(2)}%p · 마지막 비교상품 ${fmt.format(last.product_count||0)}개`;
}
function renderChangesEnhanced(){
  const c=data.strategy?.market_changes||{},items=c.items||[],flow=marketDirection(c);
  $("changes").textContent=fmt.format(c.count||0);
  $("ups").textContent=fmt.format(flow.up);
  $("downs").textContent=fmt.format(flow.down);
  $("affected").textContent=fmt.format(c.affected_variant_count||0);
  $("change-direction-copy").textContent=flow.label;
  $("change-up-bar").style.width=`${flow.upShare.toFixed(1)}%`;
  $("change-down-bar").style.width=`${flow.downShare.toFixed(1)}%`;
  $("change-up-share").textContent=`상승 ${flow.upShare.toFixed(0)}%`;
  $("change-down-share").textContent=`하락 ${flow.downShare.toFixed(0)}%`;
  $("change-direction-note").textContent=`30일 ${fmt.format(c.count||0)}개 상품 이벤트 · `
    +`변동폭이 큰 주요 ${fmt.format(Math.min(items.length,12))}건 표시`;
  if(c.latest_changed_at){
    const d=new Date(c.latest_changed_at);
    if(!Number.isNaN(d.getTime())){
      $("change-latest").textContent=d.toLocaleDateString("ko-KR",{
        month:"2-digit",day:"2-digit"
      });
    }
  }
  $("feed").innerHTML=items.length?items.slice(0,12).map(x=>{
    const delta=Number(x.delta||0),dir=delta>=0?"up":"down";
    const d=x.changed_at?new Date(x.changed_at):null;
    const when=d&&!Number.isNaN(d.getTime())
      ?d.toLocaleDateString("ko-KR",{month:"2-digit",day:"2-digit"}):"";
    return `<div class="change ${dir}"><div class="changehead">`
      +`<b>${esc(x.institution)}</b><strong>${delta>0?"+":""}${delta.toFixed(2)}%p</strong>`
      +`</div><span>${esc(x.product)} · ${Number(x.previous_max_rate).toFixed(2)} → `
      +`${Number(x.max_rate).toFixed(2)}%</span><small>${when}`
      +`${Number(x.variant_count||1)>1?` · 세부 ${fmt.format(x.variant_count)}건 동시`:""}`
      +`</small></div>`;
  }).join(""):'<div class="empty">최근 30일 비교 가능한 최고금리 변경이 없습니다.</div>';
}
function renderInsightsEnhanced(){
  const c=data.strategy?.market_changes||{},flow=marketDirection(c),p=prefData(12);
  const regional=regionAverages(products12),strongest=regional[0],weakest=regional.at(-1);
  const stats=ratesStats(products12),own=products12
    .filter(x=>x.institution===OUR_INSTITUTION).sort((a,b)=>b.max-a.max)[0]||null;
  const pts=(data.strategy?.rate_trend?.points||[])
    .filter(x=>Number.isFinite(Number(x.mean_max_rate)));
  const meanDelta=pts.length>1
    ?Number(pts.at(-1).mean_max_rate)-Number(pts[0].mean_max_rate):null;
  const premium=Number.isFinite(stats.max)&&Number.isFinite(stats.mean)?stats.max-stats.mean:null;
  const ownMeanGap=own&&Number.isFinite(stats.mean)?own.max-stats.mean:null;
  const ownTopGap=own&&Number.isFinite(stats.top10)?own.max-stats.top10:null;
  const regionalSpread=strongest&&weakest?strongest.rate-weakest.rate:null;
  const topPref=p.items[0],secondPref=p.items[1];
  const directionAction=flow.label==="하락 우세"
    ?"시장 최고 추격보다 TOP10 진입선과 만기 방어 목적을 분리해 금리를 설계합니다."
    :flow.label==="상승 우세"
      ?"상위권 이탈 속도와 신규자금 확보 목적을 함께 보고 금리 인상폭을 비교합니다."
      :"평균만 보지 말고 TOP10·TOP5의 국지적 움직임을 함께 확인합니다.";
  const items=[
    {icon:"↕",tag:"시장 방향",title:`30일 ${flow.label}`,
      text:`상승 ${fmt.format(flow.up)}건 · 하락 ${fmt.format(flow.down)}건`
        +(Number.isFinite(meanDelta)?` · 63일 평균 ${formatBp(meanDelta)}`:""),
      action:directionAction},
    {icon:"⌁",tag:"경쟁 강도",
      title:Number.isFinite(premium)?`시장 상단 프리미엄 ${formatBp(premium)}`:"상단 격차 계산 중",
      text:Number.isFinite(stats.top10)&&Number.isFinite(stats.mean)
        ?`시장 최고 ${stats.max.toFixed(2)}% · TOP10 ${stats.top10.toFixed(2)}% · 평균 ${stats.mean.toFixed(2)}%`
        :"현재 비교상품이 필요합니다.",
      action:Number.isFinite(premium)&&premium>=.30
        ?"최고금리 1등 추격 비용이 큰 구간이므로 TOP10 진입선 중심 시나리오를 우선 비교합니다."
        :"최고·TOP10·평균 간격을 함께 보고 필요한 순위만큼만 금리를 조정합니다."},
    {icon:"◎",tag:"당사 위치",
      title:own&&Number.isFinite(ownMeanGap)
        ?`고려저축은행 · 평균 대비 ${formatBp(ownMeanGap)}`:"당사 비교상품 확인 중",
      text:own&&Number.isFinite(ownTopGap)
        ?`현재 ${own.max.toFixed(2)}% · TOP10 대비 ${formatBp(ownTopGap)}`
        :"12개월 당사 최고금리 비교가 필요합니다.",
      action:"현재금리 대비 5bp·10bp·15bp 안을 하단 시뮬레이터에서 순위와 비용으로 비교합니다."},
    {icon:"◇",tag:"지역 편차",
      title:Number.isFinite(regionalSpread)?`지역 평균 편차 ${formatBp(regionalSpread)}`:"지역 데이터 확인 중",
      text:strongest&&weakest
        ?`${strongest.region} ${strongest.rate.toFixed(2)}% ↔ ${weakest.region} ${weakest.rate.toFixed(2)}%`
        :"본점 소재지 정보가 있는 비교상품이 필요합니다.",
      action:"본점 소재지 참고값이며 판매 가능 지역으로 해석하지 않고 지역 경쟁강도 참고에만 사용합니다."},
    {icon:"≡",tag:"우대조건 구조",
      title:topPref?`${topPref.label} ${topPref.ratio.toFixed(0)}%`:"우대조건 데이터 확인 중",
      text:topPref
        ?`조건 기재 상품 기준${secondPref?` · ${secondPref.label} ${secondPref.ratio.toFixed(0)}%`:""}`
        :"표준 분류 가능한 우대조건이 필요합니다.",
      action:"보편 조건과 차별 조건을 분리해 기본금리와 우대금리의 역할을 설계합니다."}
  ];
  $("insights").innerHTML=items.map(x=>
    `<div class="insight"><div class="ii">${x.icon}</div><div><em>${esc(x.tag)}</em>`
      +`<b>${esc(x.title)}</b><span>${esc(x.text)}</span>`
      +`<small>기획 포인트 · ${esc(x.action)}</small></div></div>`
  ).join("");
}
function renderPlanningContext(comp,stats,own){
  const flow=marketDirection(data.strategy?.market_changes||{});
  $("plan-flow").textContent=flow.label;
  $("plan-flow-note").textContent=`30일 상승 ${fmt.format(flow.up)} · 하락 ${fmt.format(flow.down)}`;
  $("plan-market-max").textContent=Number.isFinite(stats.max)?`${stats.max.toFixed(2)}%`:"—";
  $("plan-market-max-note").textContent=`${simTerm}개월 ${fmt.format(comp.length)}개 비교상품`;
  $("plan-market-mean").textContent=Number.isFinite(stats.mean)?`${stats.mean.toFixed(2)}%`:"—";
  $("plan-market-mean-note").textContent=Number.isFinite(stats.median)
    ?`중앙값 ${stats.median.toFixed(2)}%`:"비교군 없음";
  $("plan-top10").textContent=Number.isFinite(stats.top10)?`${stats.top10.toFixed(2)}%`:"—";
  $("plan-top10-note").textContent="상품 대표 최고금리 기준";
  $("plan-own").textContent=own?`${own.max.toFixed(2)}%`:"—";
  $("plan-own-note").textContent=own?own.product:`${simTerm}개월 당사 상품 없음`;
}
""".lstrip()
    text = _replace_once(
        text,
        "function setMarker(id,value,min,max){",
        behavior + "function setMarker(id,value,min,max){",
        "layout.enhanced_behavior",
    )
    text = _replace_once(
        text,
        '  $("sim-max").textContent=',
        '  renderPlanningContext(comp,stats,own);\n  $("sim-max").textContent=',
        "layout.planning_context_call",
    )
    text = _replace_once(
        text,
        "renderHealth();renderChanges();renderTrend();",
        "renderHealth();renderChangesEnhanced();renderTrendEnhanced();",
        "layout.boot_market_flow",
    )
    text = _replace_once(
        text,
        "renderPrefs();renderTermStrip();renderInsights();updateSim()",
        "renderPrefs();renderTermStrip();renderInsightsEnhanced();updateSim()",
        "layout.boot_insights",
    )
    return text


def adapt_strategy_refinements(text: str) -> str:
    """예측엔진·전국 지도와 의사결정 순서의 UI를 후행 보정한다."""
    text = _adapt_prediction_panel(text)
    text = _adapt_information_flow(text)
    text = _adapt_national_map_readability(text)
    text = _adapt_dashboard_flow_css(text)
    return _adapt_dashboard_flow_behavior(text)
