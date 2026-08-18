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
    assert "수집 데이터 기준 최고금리" in html


def test_h3_ranking_denominators_are_sector_namespaced_and_explicit() -> None:
    html = _html()

    assert '`${x.sector}\\0${x.institution}`' in html
    assert 'id="ranking-basis"' in html
    assert "sector + stable product 대표" in html
    assert 'id="top5-copy"' in html
    assert "rateScopeText(r.rateScope)" in html
    assert "availabilityText(r.availabilityScope)" in html
    assert "max_rate ?? base_rate" not in html
    assert 'rateBasis:look("strategy_rate_basis"' in html
    assert "strategyRateBasisText(r.rateBasis)" in html


def test_h3_geography_uses_separate_sector_layers() -> None:
    html = _html()

    assert 'mapSector="savings_bank"' in html
    assert 'id="map-layer-tabs"' in html
    label_expr = (
        'key==="savings_bank"?"저축은행 본점":key==="cu"?"신협 조회지역":'
        'key==="kfcc"?"새마을금고 공시지역":key==="nh_local"?"농·축협 점포"'
    )
    assert label_expr in html
    assert "function geoProducts(sector,term=12)" in html
    geo_key = (
        '`${sector}\\0${r.productId}\\0${term}\\0'
        '${expectedBasis}\\0${geo}\\0${district}`'
    )
    assert geo_key in html
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


def test_h3_top5_uses_row_level_scope_and_availability_evidence() -> None:
    html = _html()

    assert 'availabilityScope:look("availability_scope"' in html
    assert 'geoBasis:look("geo_basis"' in html
    assert 'rateScope:look("rate_scope"' in html
    assert 'joinChannel:look("join_channel"' in html
    assert "rateScopeText(r.rateScope)" in html
    assert "availabilityText(r.availabilityScope)" in html
    assert 'r.joinChannel?`가입채널 ${r.joinChannel}`:null' in html
    assert 'source_max_rate:"원천 최고금리"' in html
    assert 'nh_ejoy_base_plus_add:"기본금리 + e-joy 우대"' in html
    assert 'collected_base_rate:"수집 기본금리"' in html


def test_h3_map_fails_safe_when_sector_has_multiple_geo_bases() -> None:
    html = _html()

    assert 'function hasSingleGeoBasis(key)' in html
    assert 'bases.length!==1)return[]' in html
    assert 'r.geoBasis!==expectedBasis' in html
    assert '${expectedBasis}\\0${geo}' in html


def test_h3_ranking_rejects_missing_stable_product_identity() -> None:
    html = _html()

    assert '||!r.productId)continue;' in html
    assert 'const key=`${r.sector}\\0${r.productId}\\0${term}`' in html
    assert 'r.productId||r.product' not in html


def test_h3_nh_local_map_uses_outlet_address_without_busan_inference() -> None:
    html = _html()

    assert '["savings_bank","cu","kfcc","nh_local"].includes(key)' in html
    assert '"농·축협 점포 주소별 금리 분포"' in html
    map_copy = (
        '"공식 점포 주소별 stable product 수집 데이터 기준 최고금리 평균 · '
        '가입 가능 지역으로 해석하지 않음"'
    )
    assert map_copy in html
    assert (
        '`농·축협 · ${geoBasis} · SGIS 2020 시도 경계 · district 추정 없음`'
        in html
    )
    assert 'clickable=savings&&x.region==="부산"' in html


def test_h3_kfcc_map_is_collection_geography_not_join_eligibility() -> None:
    html = _html()

    assert '"새마을금고 공시 소재지별 금리 분포"' in html
    assert (
        '"중앙 공시의 기관별 수집 데이터 기준 최고금리 평균 · '
        '가입 가능 지역으로 해석하지 않음"'
    ) in html
    assert (
        '`새마을금고 · ${geoBasis} · SGIS 2020 시도 경계 · district 추정 없음`'
        in html
    )
    assert "기관 공시금리를 배치한 지역이며 가입 가능 지역으로 해석하지 않음" in html
