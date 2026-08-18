def _html() -> str:
    with open("web/templates/strategy.html", encoding="utf-8") as handle:
        return handle.read()


def test_h2_exposes_three_market_modes_and_sector_capabilities() -> None:
    html = _html()

    assert 'data-market-mode="savings_bank"' in html
    assert 'data-market-mode="mutual_finance"' in html
    assert 'data-market-mode="combined"' in html
    assert 'data-sector="cu" checked' in html
    assert 'data-sector="kfcc">' in html
    assert 'data-sector="nh_local">' in html
    assert 'data-sector="kfcc" disabled' not in html
    assert 'data-sector="nh_local" disabled' not in html
    assert "function activeSectors()" in html
    assert 'marketMode==="mutual_finance"' in html
    assert 'marketMode==="savings_bank"' in html


def test_h2_uses_strategy_universe_instead_of_hardcoded_support() -> None:
    html = _html()

    assert "strategyUniverse=packed.strategy_universe||null" in html
    assert "universeSector(input.dataset.sector)" in html
    assert "enabled=!!meta?.selectable" in html
    assert "수집 데이터 기준 최고금리" in html
    assert "원천 최고금리 우선" in html
    assert "미기재 시 수집 기본금리" in html
    assert "meta.blocked_reason" in html
    assert "신협 6개월 공시 데이터 없음" in html


def test_h2_aggregates_only_active_strategy_rate_sectors() -> None:
    html = _html()

    assert "const sectors=activeSectors()" in html
    assert "const allowed=new Set(sectors)" in html
    assert "!allowed.has(r.sector)" in html
    assert 'const key=`${r.sector}\\0${r.productId}\\0${term}`' in html
    assert "sector:r.sector" in html
    assert "max_rate ?? base_rate" not in html
    assert 'rateBasis:look("strategy_rate_basis"' in html


def test_h2_does_not_relabel_savings_history_as_mutual_history() -> None:
    html = _html()

    assert 'id="market-flow"' in html
    assert "이력 추이는 저축은행 정상 수집일 기준" in html
    assert '$("market-flow").hidden=mutualOnly' in html


def test_h2_locks_our_bank_simulator_in_mutual_only_mode() -> None:
    html = _html()

    assert 'id="sim-scope-warning" hidden' in html
    assert 'id="sim-form"' in html
    assert "상호금융 단독 모드에서는 고려저축은행 기준" in html
    assert '$("sim-form").hidden=mutualOnly' in html


def test_h2_term_cards_explicitly_show_no_data() -> None:
    html = _html()

    assert 'p.length?`평균 · ${fmt.format(p.length)}상품`:"데이터 없음"' in html
