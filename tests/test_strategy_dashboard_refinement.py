"""전략 대시보드 후행 UI refinement 계약."""

from rate_monitor.services.site_service import (
    DEFAULT_STRATEGY_TEMPLATE,
    adapt_strategy_korea_map_template,
)
from rate_monitor.services.strategy_contract_service import adapt_strategy_template


def _html() -> str:
    text = adapt_strategy_template(DEFAULT_STRATEGY_TEMPLATE.read_text(encoding="utf-8"))
    return adapt_strategy_korea_map_template(text)


def test_prediction_engine_is_hidden_until_explicit_button_click() -> None:
    html = _html()

    assert 'id="prediction-toggle"' in html
    assert 'aria-expanded="false"' in html
    assert 'aria-controls="prediction-panel"' in html
    assert '>예측엔진 보기</button>' in html
    assert 'id="prediction-panel" class="prediction-panel" hidden' in html
    assert "function togglePredictionPanel()" in html
    assert (
        'button.textContent=opening?"예측엔진 닫기":"예측엔진 보기"'
        in html
    )
    assert (
        '$("prediction-toggle").addEventListener("click",togglePredictionPanel)'
        in html
    )


def test_prediction_engine_explains_model_and_evidence_scope() -> None:
    html = _html()

    assert "쉽게 보면" in html
    assert "새로 들어오는 돈과 만기 후 남는 돈을 섞지 않습니다" in html
    assert "모형 근거 · 어떤 부분을 어디서 가져왔나" in html
    assert "Fed FEDS 2013 · Sticky Deposit Rates" in html
    assert "NY Fed 2025 · Deposit Flightiness" in html
    assert "한국은행 BOK 이슈노트 2023-33" in html
    assert "exp / logistic 함수" in html
    assert "β·γ 민감도 숫자" in html
    assert "외부 논문값이나 고려저축은행 실적 추정치가 아니라" in html
    assert "Fed·한국은행의 공식 예측식을 그대로 복제한 것이 아니라" in html
    assert (
        "https://www.federalreserve.gov/pubs/feds/2013/201380/index.html"
        in html
    )
    assert (
        "the-rise-in-deposit-flightiness-and-its-implications-for-"
        "financial-stability"
        in html
    )
    assert "nttId=10081072" in html


def test_national_map_gives_more_width_to_map_and_offsets_labels() -> None:
    html = _html()

    assert (
        ".primary:not(.busan-focus){grid-template-columns:minmax(470px,.86fr) "
        "minmax(590px,1.14fr)}"
    ) in html
    assert (
        ".primary:not(.busan-focus) .tablewrap table{min-width:540px}"
        in html
    )
    assert ".primary:not(.busan-focus) .node-label{font-size:14px" in html
    assert ".primary:not(.busan-focus) .node-rate{font-size:15px" in html
    assert 'const koreaLabelOffsets={"서울":[-28,-24,"end"]' in html
    assert '"부산":[30,10,"start"]' in html
    assert "preset=koreaLabelOffsets[x.region]" in html
    assert 'lineX=anchor==="end"?lx+7:anchor==="start"?lx-7:lx' in html
    assert 'x2="${lineX}" y2="${lineY}"' in html


def test_national_map_refinement_does_not_change_busan_focus_contract() -> None:
    html = _html()

    assert (
        ".primary.busan-focus{grid-template-columns:minmax(720px,1.45fr)"
        in html
    )
    assert (
        'document.querySelector(".primary")?.classList.add("busan-focus")'
        in html
    )
    assert (
        'document.querySelector(".primary")?.classList.remove("busan-focus")'
        in html
    )
    assert 'setAttribute("viewBox","130 -5 450 675")' in html
    assert 'setAttribute("viewBox","0 0 800 757")' in html
