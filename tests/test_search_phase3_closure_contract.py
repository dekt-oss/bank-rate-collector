from pathlib import Path


SITE = Path("web/templates/site.html")


def site_text() -> str:
    return SITE.read_text(encoding="utf-8")


def test_exact_12_month_business_presets_are_first_and_explicit() -> None:
    text = site_text()
    deposit = text.index('id: "exact12-dep", label: "1년 예금 · 12개월"')
    savings = text.index('id: "exact12-sav", label: "1년 적금 · 12개월"')
    old_first = text.index('id: "sb-dep", label: "부산 저축은행 · 7~12개월 정기예금"')
    assert deposit < savings < old_first
    assert 'pick: { type: ["term_deposit"], term: ["7-12"] }' in text
    assert 'pick: { type: ["installment_savings"], term: ["7-12"] }' in text
    assert text.count("values: { tmin: 12, tmax: 12 }") == 2


def test_legacy_preset_labels_match_their_real_bucket() -> None:
    text = site_text()
    for label in (
        "부산 저축은행 · 7~12개월 정기예금",
        "부산 저축은행 · 7~12개월 적금",
        "부산 상호금융 · 7~12개월 정기예금",
        "부산 상호금융 · 7~12개월 적금",
    ):
        assert label in text
    assert 'label: "부산 저축은행 · 1년 정기예금"' not in text
    assert 'label: "부산 저축은행 · 1년 적금"' not in text
    assert 'label: "부산 상호금융 · 1년 정기예금"' not in text
    assert 'label: "부산 상호금융 · 1년 적금"' not in text
    assert text.count("values: { tmin: null, tmax: null }") == 4


def test_preset_apply_count_and_active_share_pick_plus_value_contract() -> None:
    text = site_text()
    assert "const rowMatchesPreset = (r, p) =>" in text
    assert "ALL.filter((r) => rowMatchesPreset(r, p)).length" in text
    assert "const presetOn = (p) =>" in text
    assert "Object.entries(p.values || {}).every(([k, v]) => state[k] === v)" in text
    assert "Object.entries(p.values || {}).forEach(([k, v]) =>" in text
    assert '$("tmin").value = state.tmin == null ? "" : String(state.tmin);' in text
    assert '$("tmax").value = state.tmax == null ? "" : String(state.tmax);' in text


def test_exact_business_presets_preserve_region_and_sector() -> None:
    text = site_text()
    start = text.index('id: "exact12-dep"')
    end = text.index('id: "sb-dep"')
    exact_block = text[start:end]
    assert "region:" not in exact_block
    assert "sector:" not in exact_block
    assert "type:" in exact_block
    assert "term:" in exact_block


def test_default_universe_still_has_no_exact_term_range() -> None:
    text = site_text()
    assert 'Object.assign(state, { q: "", rmin: null, tmin: null, tmax: null,' in text
    assert 'const DEFAULT_REGIONS = ["서울", "경기", BUSAN_SIDO];' in text


def test_nested_groups_remain_select_only_narrowing_contract() -> None:
    text = site_text()
    assert "if (!state.prefTags.size) selectAllPreferenceTags();" in text
    assert "if (!state.gu.size) selectAllBusanDistricts();" in text
    assert 'if (key === "gu") {\n        selectAllBusanDistricts();' in text
    assert 'else if (key === "prefTags") {\n        selectAllPreferenceTags();' in text
