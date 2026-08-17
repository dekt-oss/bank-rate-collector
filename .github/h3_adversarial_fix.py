from pathlib import Path

html_path = Path("web/templates/strategy.html")
html = html_path.read_text(encoding="utf-8")


def once(old: str, new: str, label: str) -> None:
    global html
    count = html.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    html = html.replace(old, new, 1)


once(
    'sourceEffectiveAt:look("source_effective_at",r[c.source_effective_at]),prefStatus:',
    'sourceEffectiveAt:look("source_effective_at",r[c.source_effective_at]),joinChannel:look("join_channel",r[c.join_channel]),availabilityScope:look("availability_scope",r[c.availability_scope]),geoBasis:look("geo_basis",r[c.geo_basis]),rateScope:look("rate_scope",r[c.rate_scope]),prefStatus:',
    "expand row evidence fields",
)

once(
    'function sectorAvailability(key){return compactMeta(metaValueList(universeSector(key),"availability_scope"),AVAILABILITY_LABELS,"가입 범위 미확인")}',
    'function sectorAvailability(key){return compactMeta(metaValueList(universeSector(key),"availability_scope"),AVAILABILITY_LABELS,"가입 범위 미확인")}\nfunction availabilityText(value){return AVAILABILITY_LABELS[value]||String(value||"가입 범위 미확인")}\nfunction rateScopeText(value){return RATE_SCOPE_LABELS[value]||String(value||"비교 단위 미확인")}\nfunction hasSingleGeoBasis(key){return metaValueList(universeSector(key),"geo_basis").length===1}',
    "row evidence formatters",
)

once(
    'function activeGeoSectors(){return activeSectors().filter(key=>["savings_bank","cu"].includes(key)&&metaValueList(universeSector(key),"geo_basis").length)}',
    'function activeGeoSectors(){return activeSectors().filter(key=>["savings_bank","cu"].includes(key)&&hasSingleGeoBasis(key))}',
    "single geo basis gate",
)

once(
    'sourceEffectiveAt:null,prefKnown:false,tags:new Set',
    'sourceEffectiveAt:null,joinChannel:null,availabilityScope:null,geoBasis:null,rateScope:null,prefKnown:false,tags:new Set',
    "aggregate evidence initialization",
)

once(
    'p.sourceEffectiveAt=r.sourceEffectiveAt;p.region=region(r.region)||p.region;p.district=r.district||p.district}',
    'p.sourceEffectiveAt=r.sourceEffectiveAt;p.joinChannel=r.joinChannel;p.availabilityScope=r.availabilityScope;p.geoBasis=r.geoBasis;p.rateScope=r.rateScope;p.region=region(r.region)||p.region;p.district=r.district||p.district}',
    "aggregate representative evidence",
)

once(
    'const spread=Number.isFinite(r.base)?r.max-r.base:null,provenance=[sectorLabel(r.sector),sectorRateScope(r.sector),r.sourceId||"원천 미확인",formatDate(r.sourceEffectiveAt),sectorAvailability(r.sector)].join(" · ");',
    'const spread=Number.isFinite(r.base)?r.max-r.base:null,provenance=[sectorLabel(r.sector),rateScopeText(r.rateScope),r.sourceId||"원천 미확인",formatDate(r.sourceEffectiveAt),availabilityText(r.availabilityScope),r.joinChannel?`가입채널 ${r.joinChannel}`:null].filter(Boolean).join(" · ");',
    "TOP5 row-level provenance",
)

old_geo = 'function geoProducts(sector,term=12){const m=new Map;for(const r of allRows){if(r.sector!==sector||r.type!=="term_deposit"||r.term!==term||!Number.isFinite(r.max)||!r.productId)continue;const geo=region(r.region);if(!geo||!coords[geo])continue;const district=sector==="savings_bank"?(r.district||""):"",key=`${sector}\\0${r.productId}\\0${term}\\0${geo}\\0${district}`,freshness=String(r.sourceEffectiveAt||""),old=m.get(key);if(!old||r.max>old.max||(r.max===old.max&&freshness>String(old.sourceEffectiveAt||"")))m.set(key,{sector,productId:r.productId,institution:r.institution,product:r.product,term,region:geo,district:r.district||null,max:r.max,sourceEffectiveAt:r.sourceEffectiveAt})}return[...m.values()]}'
new_geo = 'function geoProducts(sector,term=12){const bases=metaValueList(universeSector(sector),"geo_basis");if(bases.length!==1)return[];const expectedBasis=bases[0],m=new Map;for(const r of allRows){if(r.sector!==sector||r.type!=="term_deposit"||r.term!==term||!Number.isFinite(r.max)||!r.productId||r.geoBasis!==expectedBasis)continue;const geo=region(r.region);if(!geo||!coords[geo])continue;const district=sector==="savings_bank"?(r.district||""):"",key=`${sector}\\0${r.productId}\\0${term}\\0${expectedBasis}\\0${geo}\\0${district}`,freshness=String(r.sourceEffectiveAt||""),old=m.get(key);if(!old||r.max>old.max||(r.max===old.max&&freshness>String(old.sourceEffectiveAt||"")))m.set(key,{sector,productId:r.productId,institution:r.institution,product:r.product,term,region:geo,district:r.district||null,geoBasis:expectedBasis,max:r.max,sourceEffectiveAt:r.sourceEffectiveAt})}return[...m.values()]}'
once(old_geo, new_geo, "geo basis row gate")

once(
    'const busan=clickable=>document.querySelector(\'[data-region="부산"]\');const busanNode=savings?busan(true):null;',
    'const busanNode=savings?document.querySelector(\'[data-region="부산"]\'):null;',
    "clean busan selector",
)

html_path.write_text(html, encoding="utf-8")

test_path = Path("tests/test_strategy_mutual_finance_h3.py")
test = test_path.read_text(encoding="utf-8")
test += '''\n\ndef test_h3_top5_uses_row_level_scope_and_availability_evidence() -> None:\n    html = _html()\n\n    assert 'availabilityScope:look("availability_scope"' in html\n    assert 'geoBasis:look("geo_basis"' in html\n    assert 'rateScope:look("rate_scope"' in html\n    assert 'joinChannel:look("join_channel"' in html\n    assert "rateScopeText(r.rateScope)" in html\n    assert "availabilityText(r.availabilityScope)" in html\n    assert 'r.joinChannel?`가입채널 ${r.joinChannel}`:null' in html\n\n\ndef test_h3_map_fails_safe_when_sector_has_multiple_geo_bases() -> None:\n    html = _html()\n\n    assert 'function hasSingleGeoBasis(key)' in html\n    assert 'bases.length!==1)return[]' in html\n    assert 'r.geoBasis!==expectedBasis' in html\n    assert '${expectedBasis}\\\\0${geo}' in html\n'''
test_path.write_text(test, encoding="utf-8")
