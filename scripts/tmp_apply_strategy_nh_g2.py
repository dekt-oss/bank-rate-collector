#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:80]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


contract = "src/rate_monitor/services/strategy_contract_service.py"
template = "web/templates/strategy.html"
smoke = "scripts/strategy_preview_smoke.js"
contract_test = "tests/test_strategy_contract_service.py"
h3_test = "tests/test_strategy_mutual_finance_h3.py"

replace_once(
    contract,
    'STRATEGY_MAX_RATE_ENABLED_SECTORS = frozenset({"savings_bank", "cu"})\n',
    'STRATEGY_MAX_RATE_ENABLED_SECTORS = frozenset({"savings_bank", "cu", "nh_local"})\n'
    'STRATEGY_MAX_ONLY_PUBLISHED_SECTORS = frozenset({"nh_local"})\n',
)
replace_once(
    contract,
    '    "nh_local": "preferential_component_product_channel_linkage_unproven",\n',
    '    "nh_local": "official_ejoy_same_brc_product_term_interval_internet_variant",\n',
)
replace_once(
    contract,
    '''    "nh_local": (\n        "e-joy 인터넷 우대행은 확인됐지만 stable product·기간·인터넷 채널에 "\n        "대한 결정론적 linkage가 아직 증명되지 않음"\n    ),\n''',
    "",
)
replace_once(
    contract,
    '''    Stage H1에서는 저축은행과 신협(CU)만 실제 payload에 포함한다. KFCC/NH는\n    ``strategy_universe`` metadata에 coverage/차단 사유만 남긴다. 값 변환·금리\n    fallback을 하지 않으며 canonical columns/lookups 계약은 그대로 유지한다.\n''',
    '''    Stage G2 evidence가 열린 농·축협(NH local)도 strategy capability에 포함한다.\n    다만 NH는 기본행·e-joy 원천행까지 payload를 중복 확장하지 않고 evidence-backed\n    ``max_rate``가 있는 internet variant만 싣는다. KFCC는 metadata에 차단 사유만\n    남긴다. 값 변환·금리 fallback은 하지 않는다.\n''',
)
replace_once(
    contract,
    '''    universe = strategy_universe_metadata(table)\n    rows = []\n    for row in table.get("rows") or []:\n''',
    '''    universe = strategy_universe_metadata(table)\n    max_index = source_columns.get("max_rate")\n    rows = []\n    for row in table.get("rows") or []:\n''',
)
replace_once(
    contract,
    '''        if (\n            sector in STRATEGY_MAX_RATE_ENABLED_SECTORS\n            and product_type == STRATEGY_PRODUCT_TYPE\n            and term in STRATEGY_TERMS\n        ):\n            rows.append(row)\n''',
    '''        if (\n            sector in STRATEGY_MAX_RATE_ENABLED_SECTORS\n            and product_type == STRATEGY_PRODUCT_TYPE\n            and term in STRATEGY_TERMS\n        ):\n            if sector in STRATEGY_MAX_ONLY_PUBLISHED_SECTORS and (\n                max_index is None or not _rate_present(row[max_index])\n            ):\n                continue\n            rows.append(row)\n''',
)

replace_once(
    template,
    'function activeGeoSectors(){return activeSectors().filter(key=>["savings_bank","cu"].includes(key)&&hasSingleGeoBasis(key))}\n',
    'function activeGeoSectors(){return activeSectors().filter(key=>["savings_bank","cu","nh_local"].includes(key)&&hasSingleGeoBasis(key))}\n',
)
replace_once(
    template,
    'function mapLayerLabel(key){return key==="savings_bank"?"저축은행 본점":key==="cu"?"신협 조회지역":sectorLabel(key)}\n',
    'function mapLayerLabel(key){return key==="savings_bank"?"저축은행 본점":key==="cu"?"신협 조회지역":key==="nh_local"?"농·축협 점포":sectorLabel(key)}\n',
)
replace_once(
    template,
    '''  const savings=sector==="savings_bank",geoBasis=sectorGeoBasis(sector),geoRows=geoProducts(sector,12),a=regionAverages(geoRows),top=a[0]?.region;\n  svg.setAttribute("aria-label",savings?"저축은행 본점 소재지별 금리 분포 지도":"신협 원천 조회지역별 금리 분포 지도");$("map-title").textContent=savings?"전국 본점 소재지별 금리 분포":"신협 조회지역별 금리 분포";$("map-copy").textContent=savings?"본점 소재지별 stable product 대표 최고금리 평균 · 부산을 누르면 구별 지도 확대":"공식 source_query_region별 stable product 최고금리 관측 평균 · 본점/판매 가능 지역으로 해석하지 않음";$("map-chip").textContent=`12개월 · ${fmt.format(a.length)}지역`;$("map-mode-label").textContent=savings?`저축은행 · ${geoBasis} · SGIS 2020 시도 경계 · 제주 inset`:`신협 · ${geoBasis} · SGIS 2020 시도 경계 · district 추정 없음`;$("footer-geo").innerHTML=savings?`<b>지역 기준</b> · 저축은행 ${esc(geoBasis)} — 판매 가능 지역으로 해석하지 않음`:`<b>지역 기준</b> · 신협 ${esc(geoBasis)} — 본점 소재지·판매 가능 지역으로 해석하지 않음`;\n''',
    '''  const savings=sector==="savings_bank",cu=sector==="cu",nhLocal=sector==="nh_local",geoBasis=sectorGeoBasis(sector),geoRows=geoProducts(sector,12),a=regionAverages(geoRows),top=a[0]?.region;\n  const mapAria=savings?"저축은행 본점 소재지별 금리 분포 지도":cu?"신협 원천 조회지역별 금리 분포 지도":"농·축협 점포 주소별 금리 분포 지도";\n  const mapTitle=savings?"전국 본점 소재지별 금리 분포":cu?"신협 조회지역별 금리 분포":"농·축협 점포 주소별 금리 분포";\n  const mapCopy=savings?"본점 소재지별 stable product 대표 최고금리 평균 · 부산을 누르면 구별 지도 확대":cu?"공식 source_query_region별 stable product 최고금리 관측 평균 · 본점/판매 가능 지역으로 해석하지 않음":"공식 점포 주소별 stable product 최고금리 관측 평균 · 가입 가능 지역으로 해석하지 않음";\n  const mapModeCopy=savings?`저축은행 · ${geoBasis} · SGIS 2020 시도 경계 · 제주 inset`:cu?`신협 · ${geoBasis} · SGIS 2020 시도 경계 · district 추정 없음`:`농·축협 · ${geoBasis} · SGIS 2020 시도 경계 · district 추정 없음`;\n  const footerCopy=savings?`<b>지역 기준</b> · 저축은행 ${esc(geoBasis)} — 판매 가능 지역으로 해석하지 않음`:cu?`<b>지역 기준</b> · 신협 ${esc(geoBasis)} — 본점 소재지·판매 가능 지역으로 해석하지 않음`:`<b>지역 기준</b> · 농·축협 ${esc(geoBasis)} — 가입 가능 지역으로 해석하지 않음`;\n  svg.setAttribute("aria-label",mapAria);$("map-title").textContent=mapTitle;$("map-copy").textContent=mapCopy;$("map-chip").textContent=`12개월 · ${fmt.format(a.length)}지역`;$("map-mode-label").textContent=mapModeCopy;$("footer-geo").innerHTML=footerCopy;\n''',
)

replace_once(
    smoke,
    '''async function assertNoHorizontalOverflow(page, label) {\n''',
    '''async function strategySectorMeta(page, sector) {\n  return page.evaluate(async (key) => {\n    const response = await fetch("data/strategy-table.json");\n    if (!response.ok) throw new Error(`strategy-table.json HTTP ${response.status}`);\n    const packed = await response.json();\n    return packed.strategy_universe?.sectors?.[key] || null;\n  }, sector);\n}\n\nasync function assertNoHorizontalOverflow(page, label) {\n''',
)
replace_once(
    smoke,
    '''  invariant(await page.locator('[data-sector="kfcc"]').isDisabled(), "새마을금고 selector가 잘못 활성화됨");\n  invariant(await page.locator('[data-sector="nh_local"]').isDisabled(), "농·축협 selector가 잘못 활성화됨");\n''',
    '''  invariant(await page.locator('[data-sector="kfcc"]').isDisabled(), "새마을금고 selector가 잘못 활성화됨");\n  const nhMeta = await strategySectorMeta(page, "nh_local");\n  invariant(nhMeta?.max_rate_capability === true, "농·축협 최고금리 capability가 열리지 않음");\n  invariant(\n    (await page.locator('[data-sector="nh_local"]').isDisabled()) === !nhMeta.selectable,\n    "농·축협 selector가 strategy_universe.selectable과 불일치함",\n  );\n''',
)
replace_once(
    smoke,
    '''  invariant(await page.locator("#map-back").isHidden(), "신협 지도에서 부산 drill-down 복귀 버튼이 노출됨");\n\n  await selectMode(page, "combined", "저축은행 + 상호금융");\n''',
    '''  invariant(await page.locator("#map-back").isHidden(), "신협 지도에서 부산 drill-down 복귀 버튼이 노출됨");\n\n  if (nhMeta.selectable) {\n    await page.locator('[data-sector="cu"]').uncheck();\n    await page.locator('[data-sector="nh_local"]').check();\n    await page.waitForFunction(\n      () => Number(document.getElementById("count")?.textContent.replaceAll(",", "") || 0) > 0,\n      null,\n      { timeout: 10_000 },\n    );\n    invariant(await page.locator('[data-map-sector="nh_local"]').count() === 1, "농·축협 점포주소 지도 레이어가 없음");\n    await page.locator('[data-map-sector="nh_local"]').click();\n    await page.waitForFunction(\n      () => document.getElementById("map-title")?.textContent.trim() === "농·축협 점포 주소별 금리 분포",\n      null,\n      { timeout: 10_000 },\n    );\n    invariant((await page.locator("#map-mode-label").textContent()).includes("점포 주소"), "농·축협 지도에 outlet_address 의미가 표시되지 않음");\n    invariant(await page.locator("#map-back").isHidden(), "농·축협 지도에서 부산 drill-down 복귀 버튼이 노출됨");\n    await page.locator('[data-sector="cu"]').check();\n  }\n\n  await selectMode(page, "combined", "저축은행 + 상호금융");\n''',
)
replace_once(
    smoke,
    '''  await waitForDashboard(page);\n  await assertNoHorizontalOverflow(page, "mobile savings-bank");\n''',
    '''  await waitForDashboard(page);\n  const nhMeta = await strategySectorMeta(page, "nh_local");\n  invariant(nhMeta?.max_rate_capability === true, "모바일 농·축협 최고금리 capability가 열리지 않음");\n  invariant(\n    (await page.locator('[data-sector="nh_local"]').isDisabled()) === !nhMeta.selectable,\n    "모바일 농·축협 selector가 strategy_universe.selectable과 불일치함",\n  );\n  await assertNoHorizontalOverflow(page, "mobile savings-bank");\n''',
)

replace_once(
    contract_test,
    "import sqlite3\nfrom pathlib import Path\n",
    "import sqlite3\nfrom copy import deepcopy\nfrom pathlib import Path\n",
)
replace_once(
    contract_test,
    '    assert sliced["strategy_universe"]["published_sectors"] == ["savings_bank", "cu"]\n',
    '    assert sliced["strategy_universe"]["published_sectors"] == ["savings_bank", "cu", "nh_local"]\n',
)
replace_once(
    contract_test,
    '''    assert sectors["nh_local"]["state"] == "unsupported"\n    assert sectors["nh_local"]["rate_scope"] == ["outlet"]\n    assert sectors["nh_local"]["selectable"] is False\n    assert "인터넷 채널" in sectors["nh_local"]["blocked_reason"]\n''',
    '''    assert sectors["nh_local"]["state"] == "no_max_rate_data"\n    assert sectors["nh_local"]["max_rate_capability"] is True\n    assert sectors["nh_local"]["rate_scope"] == ["outlet"]\n    assert sectors["nh_local"]["geo_basis"] == ["outlet_address"]\n    assert sectors["nh_local"]["selectable"] is False\n    assert sectors["nh_local"]["blocked_reason"] is None\n    assert sectors["nh_local"]["evidence"] == (\n        "official_ejoy_same_brc_product_term_interval_internet_variant"\n    )\n''',
)
insert_point = '''def test_strategy_table_adds_compressed_stable_product_id(tmp_path: Path) -> None:\n'''
new_test = '''def test_strategy_nh_local_publishes_only_evidence_backed_max_rows() -> None:\n    table = deepcopy(_universe_table())\n    table["rows"][4][3] = 4.15\n    table["rows"].append([3, 0, 24, None, 2, 1, 0, 1])\n\n    sliced = slice_strategy_table(table)\n    nh_meta = sliced["strategy_universe"]["sectors"]["nh_local"]\n\n    assert nh_meta["state"] == "supported"\n    assert nh_meta["selectable"] is True\n    assert nh_meta["max_rate_rows"] == 1\n    assert nh_meta["rows"] == 2\n    assert nh_meta["coverage_ratio"] == 0.5\n    assert table["rows"][4] in sliced["rows"]\n    assert table["rows"][-1] not in sliced["rows"]\n    assert table["rows"][3] not in sliced["rows"]  # KFCC remains blocked\n\n\n'''
replace_once(contract_test, insert_point, new_test + insert_point)

replace_once(
    h3_test,
    '''    assert 'key==="savings_bank"?"저축은행 본점":key==="cu"?"신협 조회지역"' in html\n''',
    '''    assert 'key==="savings_bank"?"저축은행 본점":key==="cu"?"신협 조회지역":key==="nh_local"?"농·축협 점포"' in html\n''',
)
append_test = '''\n\ndef test_h3_nh_local_map_uses_outlet_address_without_busan_inference() -> None:\n    html = _html()\n\n    assert '["savings_bank","cu","nh_local"].includes(key)' in html\n    assert '"농·축협 점포 주소별 금리 분포"' in html\n    assert '"공식 점포 주소별 stable product 최고금리 관측 평균 · 가입 가능 지역으로 해석하지 않음"' in html\n    assert '`농·축협 · ${geoBasis} · SGIS 2020 시도 경계 · district 추정 없음`' in html\n    assert 'clickable=savings&&x.region==="부산"' in html\n'''
Path(h3_test).write_text(Path(h3_test).read_text(encoding="utf-8") + append_test, encoding="utf-8")

print("Strategy NH G2 activation patch applied")
