def _html() -> str:
    with open("web/templates/strategy.html", encoding="utf-8") as handle:
        return handle.read()


def test_h3_exposes_coverage_freshness_scope_and_availability() -> None:
    html = _html()

    assert 'id="scope-evidence"' in html
    assert "meta?.latest_source_effective_at" in html
    assert '"geo_basis"' in html
    assert '"rate_scope"' in html
    assert '"availability_scope"' in html
    assert "termCoverage(meta,12)" in html
    assert "meta?.blocked_reason" in html


def test_h3_ranking_denominators_are_sector_namespaced_and_explicit() -> None:
    html = _html()

    assert '`${x.sector}\\0${x.institution}`' in html
    assert 'id="ranking-basis"' in html
    assert "sector + stable product 대표" in html
    assert 'id="top5-copy"' in html
    assert "sectorRateScope(r.sector)" in html
    assert "sectorAvailability(r.sector)" in html
    assert "max_rate ?? base_rate" not in html


def test_h3_geography_uses_separate_savings_and_cu_layers() -> None:
    html = _html()

    assert 'mapSector="savings_bank"' in html
    assert 'id="map-layer-tabs"' in html
    assert 'key==="savings_bank"?"저축은행 본점":key==="cu"?"신협 조회지역"' in html
    assert "function geoProducts(sector,term=12)" in html
    assert '`${sector}\\0${r.productId}\\0${term}\\0${geo}\\0${district}`' in html
    assert 'geoSector?regionAverages(geoProducts(geoSector,12)):[]' in html
    assert "서로 다른 geography basis는 같은 지역 평균으로 합치지 않습니다." in html


def test_h3_cu_region_is_not_relabelled_as_head_office_or_busan_district() -> None:
    html = _html()

    assert 'source_query_region:"원천 조회지역"' in html
    assert "본점/판매 가능 지역으로 해석하지 않음" in html
    assert "본점 소재지·판매 가능 지역이나 부산 구 단위로 추정하지 않습니다." in html
    assert 'clickable=savings&&x.region==="부산"' in html
    assert 'if(mapSector!=="savings_bank")return' in html
    assert 'geoProducts("savings_bank",12).filter' in html


def test_h3_mutual_only_keeps_map_but_still_locks_savings_bank_history_and_simulator() -> None:
    html = _html()

    assert '$("map-card").hidden=false' in html
    assert '$("market-flow").hidden=mutualOnly' in html
    assert '$("sim-form").hidden=mutualOnly' in html
    assert '$("trend-delta").hidden=!savingsOnly' in html
