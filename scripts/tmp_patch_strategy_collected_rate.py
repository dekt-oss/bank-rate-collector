from pathlib import Path
import re

path = Path("web/templates/strategy.html")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match, got {count}: {old[:100]!r}")
    text = text.replace(old, new, 1)


replace_once(
    '<label class="sector-toggle disabled"><input type="checkbox" data-sector="kfcc" disabled>새마을금고 <small>최고금리 미지원</small></label>',
    '<label class="sector-toggle"><input type="checkbox" data-sector="kfcc">새마을금고 <small>확인 중</small></label>',
)
replace_once(
    '<label class="sector-toggle disabled"><input type="checkbox" data-sector="nh_local" disabled>농·축협 <small>최고금리 미지원</small></label>',
    '<label class="sector-toggle"><input type="checkbox" data-sector="nh_local">농·축협 <small>확인 중</small></label>',
)
replace_once(
    '<section class="evidence-strip" id="scope-evidence" aria-label="업권별 최고금리 coverage와 데이터 기준">',
    '<section class="evidence-strip" id="scope-evidence" aria-label="업권별 수집 데이터 기준 최고금리 coverage와 산식">',
)
replace_once(
    '<footer class="foot"><span id="footer-geo"><b>지역 기준</b> · 저축은행 공시금리 — 전국 본점 기준 참고값</span><span id="footer-calc"><b>계산 기준</b> · 최고금리 NULL은 기본금리로 대체하지 않음 · 동일 금리 공동순위</span></footer>',
    '<footer class="foot"><span id="footer-geo"><b>지역 기준</b> · 저축은행 공시금리 — 전국 본점 기준 참고값</span><span id="footer-calc"><b>계산 기준</b> · 수집 데이터 기준 최고금리 · 원천 최고금리 우선 · 미기재 시 수집 기본금리 · 명시 가산만 합산</span></footer>',
)
replace_once(
    'const AVAILABILITY_LABELS={all:"전체",general:"일반",all_customers:"전체 고객",member_only:"회원 전용",members:"회원 전용",region_restricted:"지역 제한",internet_only:"인터넷 전용",unknown:"미확인"};',
    'const AVAILABILITY_LABELS={all:"전체",general:"일반",all_customers:"전체 고객",member_only:"회원 전용",members:"회원 전용",region_restricted:"지역 제한",internet_only:"인터넷 전용",unknown:"미확인"};\nconst STRATEGY_RATE_BASIS_LABELS={source_max_rate:"원천 최고금리",nh_ejoy_base_plus_add:"기본금리 + e-joy 우대",collected_base_rate:"수집 기본금리"};',
)
replace_once(
    'function rateScopeText(value){return RATE_SCOPE_LABELS[value]||String(value||"비교 단위 미확인")}',
    'function rateScopeText(value){return RATE_SCOPE_LABELS[value]||String(value||"비교 단위 미확인")}\nfunction strategyRateBasisText(value){return STRATEGY_RATE_BASIS_LABELS[value]||String(value||"산식 미확인")}',
)
replace_once(
    'max:n(r[c.max_rate]),sourceId:look("source_id",r[c.source_id])',
    'max:n(r[c.max_rate]),rateBasis:look("strategy_rate_basis",r[c.strategy_rate_basis]),sourceId:look("source_id",r[c.source_id])',
)
replace_once('<b>12M 최고금리</b>', '<b>12M 수집기준 최고</b>')
replace_once('"공식 최고금리 계약 미지원"', '"수집 데이터 기준 비교금리 미지원"')
replace_once(
    'function activeGeoSectors(){return activeSectors().filter(key=>["savings_bank","cu","nh_local"].includes(key)&&hasSingleGeoBasis(key))}',
    'function activeGeoSectors(){return activeSectors().filter(key=>["savings_bank","cu","kfcc","nh_local"].includes(key)&&hasSingleGeoBasis(key))}',
)
replace_once(
    'function mapLayerLabel(key){return key==="savings_bank"?"저축은행 본점":key==="cu"?"신협 조회지역":key==="nh_local"?"농·축협 점포":sectorLabel(key)}',
    'function mapLayerLabel(key){return key==="savings_bank"?"저축은행 본점":key==="cu"?"신협 조회지역":key==="kfcc"?"새마을금고 공시지역":key==="nh_local"?"농·축협 점포":sectorLabel(key)}',
)
replace_once(
    'function capabilityText(meta){if(!meta)return"계약 없음";if(!meta.max_rate_capability)return"최고금리 미지원";if(!meta.selectable)return"현재 비교 데이터 없음";',
    'function capabilityText(meta){if(!meta)return"계약 없음";if(!meta.strategy_rate_capability)return"수집기준 최고금리 미지원";if(!meta.selectable)return"현재 비교 데이터 없음";',
)
replace_once(
    '$("scope-status").innerHTML=`<b>최고금리 기준 · base fallback 없음</b><span>${esc(parts.join(" · "))}</span>`;',
    '$("scope-status").innerHTML=`<b>수집 데이터 기준 최고금리</b><span>원천 최고금리 우선 · 미기재 시 수집 기본금리 · 명시 가산만 합산 · ${esc(parts.join(" · "))}</span>`;',
)
replace_once(
    'rateScope:null,prefKnown:false',
    'rateScope:null,rateBasis:null,prefKnown:false',
)
replace_once(
    'p.geoBasis=r.geoBasis;p.rateScope=r.rateScope;p.region=region(r.region)||p.region;',
    'p.geoBasis=r.geoBasis;p.rateScope=r.rateScope;p.rateBasis=r.rateBasis;p.region=region(r.region)||p.region;',
)
replace_once(
    '$("top5-copy").textContent=`12개월 정기예금 · ${modeLabel()} · sector + stable product 대표 최고금리`;',
    '$("top5-copy").textContent=`12개월 정기예금 · ${modeLabel()} · sector + stable product 대표 수집기준 최고금리`;',
)
replace_once(
    '$("footer-calc").innerHTML=`<b>계산 기준</b> · ${esc(modeLabel())} evidence-backed 최고금리 · NULL은 기본금리로 대체하지 않음 · 동일 금리 공동순위`;',
    '$("footer-calc").innerHTML=`<b>계산 기준</b> · ${esc(modeLabel())} 수집 데이터 기준 최고금리 · 원천 max 우선 · 미기재 시 수집 기본금리 · 명시 가산만 합산 · 동일 금리 공동순위`;',
)
replace_once(
    'const spread=Number.isFinite(r.base)?r.max-r.base:null,provenance=[sectorLabel(r.sector),rateScopeText(r.rateScope),r.sourceId||"원천 미확인",formatDate(r.sourceEffectiveAt),availabilityText(r.availabilityScope),r.joinChannel?`가입채널 ${r.joinChannel}`:null].filter(Boolean).join(" · ");',
    'const spread=Number.isFinite(r.base)?r.max-r.base:null,provenance=[sectorLabel(r.sector),strategyRateBasisText(r.rateBasis),rateScopeText(r.rateScope),r.sourceId||"원천 미확인",formatDate(r.sourceEffectiveAt),availabilityText(r.availabilityScope),r.joinChannel?`가입채널 ${r.joinChannel}`:null].filter(Boolean).join(" · ");',
)

pattern = re.compile(
    r'  const savings=sector==="savings_bank",cu=sector==="cu",nhLocal=sector==="nh_local",geoBasis=sectorGeoBasis\(sector\),geoRows=geoProducts\(sector,12\),a=regionAverages\(geoRows\),top=a\[0\]\?\.region;\n'
    r'  const mapAria=.*?\n'
    r'  svg\.setAttribute\("aria-label",mapAria\);\$\("map-title"\)\.textContent=mapTitle;\$\("map-copy"\)\.textContent=mapCopy;\$\("map-chip"\)\.textContent=`12개월 · \$\{fmt\.format\(a\.length\)\}지역`;\$\("map-mode-label"\)\.textContent=mapModeCopy;\$\("footer-geo"\)\.innerHTML=footerCopy;',
    re.S,
)
replacement = '''  const savings=sector==="savings_bank",cu=sector==="cu",kfcc=sector==="kfcc",nhLocal=sector==="nh_local",geoBasis=sectorGeoBasis(sector),geoRows=geoProducts(sector,12),a=regionAverages(geoRows),top=a[0]?.region;
  const mapAria=savings?"저축은행 본점 소재지별 금리 분포 지도":cu?"신협 원천 조회지역별 금리 분포 지도":kfcc?"새마을금고 공시 소재지별 금리 분포 지도":"농·축협 점포 주소별 금리 분포 지도";
  const mapTitle=savings?"전국 본점 소재지별 금리 분포":cu?"신협 조회지역별 금리 분포":kfcc?"새마을금고 공시 소재지별 금리 분포":"농·축협 점포 주소별 금리 분포";
  const mapCopy=savings?"본점 소재지별 stable product 대표 최고금리 평균 · 부산을 누르면 구별 지도 확대":cu?"공식 source_query_region별 stable product 최고금리 관측 평균 · 본점/판매 가능 지역으로 해석하지 않음":kfcc?"중앙 공시의 기관별 수집 데이터 기준 최고금리 평균 · 가입 가능 지역으로 해석하지 않음":"공식 점포 주소별 stable product 수집 데이터 기준 최고금리 평균 · 가입 가능 지역으로 해석하지 않음";
  const mapModeCopy=savings?`저축은행 · ${geoBasis} · SGIS 2020 시도 경계 · 제주 inset`:cu?`신협 · ${geoBasis} · SGIS 2020 시도 경계 · district 추정 없음`:kfcc?`새마을금고 · ${geoBasis} · SGIS 2020 시도 경계 · district 추정 없음`:`농·축협 · ${geoBasis} · SGIS 2020 시도 경계 · district 추정 없음`;
  const footerCopy=savings?`<b>지역 기준</b> · 저축은행 ${esc(geoBasis)} — 판매 가능 지역으로 해석하지 않음`:cu?`<b>지역 기준</b> · 신협 ${esc(geoBasis)} — 본점 소재지·판매 가능 지역으로 해석하지 않음`:kfcc?`<b>지역 기준</b> · 새마을금고 ${esc(geoBasis)} — 기관 공시금리를 배치한 지역이며 가입 가능 지역으로 해석하지 않음`:`<b>지역 기준</b> · 농·축협 ${esc(geoBasis)} — 가입 가능 지역으로 해석하지 않음`;
  svg.setAttribute("aria-label",mapAria);$("map-title").textContent=mapTitle;$("map-copy").textContent=mapCopy;$("map-chip").textContent=`12개월 · ${fmt.format(a.length)}지역`;$("map-mode-label").textContent=mapModeCopy;$("footer-geo").innerHTML=footerCopy;'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(f"renderKoreaMap block patch failed: {count}")

path.write_text(text, encoding="utf-8")
