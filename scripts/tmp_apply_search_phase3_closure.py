from __future__ import annotations

from pathlib import Path

PATH = Path("web/templates/site.html")
START = "  const COND_PRESETS = [\n"
END = "  const shownLimit = () => {\n"

NEW = r'''  const PRESET_VALUE_DEFAULTS = { tmin: null, tmax: null };
  const COND_PRESETS = [
    // 업무에서 가장 자주 보는 exact 12개월 두 조건. 지역/업권은 지금 고른
    // 범위를 보존하고, 상품유형 + 기간만 정확히 12개월로 좁힌다.
    { id: "exact12-dep", label: "1년 예금 · 12개월", business: true,
      pick: { type: ["term_deposit"], term: ["7-12"] },
      values: { tmin: 12, tmax: 12 } },
    { id: "exact12-sav", label: "1년 적금 · 12개월", business: true,
      pick: { type: ["installment_savings"], term: ["7-12"] },
      values: { tmin: 12, tmax: 12 } },
    { id: "sb-dep", label: "부산 저축은행 · 7~12개월 정기예금",
      pick: { region: ["부산"], sector: ["savings_bank"],
              type: ["term_deposit"], term: ["7-12"] },
      values: { tmin: null, tmax: null } },
    { id: "sb-sav", label: "부산 저축은행 · 7~12개월 적금",
      pick: { region: ["부산"], sector: ["savings_bank"],
              type: ["installment_savings"], term: ["7-12"] },
      values: { tmin: null, tmax: null } },
    { id: "mg-dep", label: "부산 상호금융 · 7~12개월 정기예금",
      pick: { region: ["부산"], sector: ["nh_local", "cu", "kfcc"],
              type: ["term_deposit"], term: ["7-12"] },
      values: { tmin: null, tmax: null } },
    { id: "mg-sav", label: "부산 상호금융 · 7~12개월 적금",
      pick: { region: ["부산"], sector: ["nh_local", "cu", "kfcc"],
              type: ["installment_savings"], term: ["7-12"] },
      values: { tmin: null, tmax: null } },
  ];

  const presetOwnValue = (p, key) =>
    Object.prototype.hasOwnProperty.call(p.values || {}, key) ? p.values[key] : state[key];

  // 프리셋 건수는 '프리셋 자체의 대략적 모집단'이 아니라 지금 화면에서
  // 실제로 눌렀을 때 나올 모집단을 센다. 프리셋이 지정하지 않은 조건은 현재
  // 상태를 보존하고, 지정한 pick/value만 target state로 덮어쓴다.
  const rowMatchesPreset = (r, p) => {
    const effective = Object.fromEntries(GROUPS.map((g) => [
      g.key,
      new Set(Object.prototype.hasOwnProperty.call(p.pick, g.key)
        ? p.pick[g.key] : state.picked[g.key]),
    ]));
    if (GROUPS.some((g) => effective[g.key].size === 0)) return false;

    const busanEffective = effective.region.has(BUSAN_SIDO);
    const guNarrowed = busanEffective && state.gu.size > 0 && state.gu.size < BUSAN.length;
    if (guNarrowed && r.region === BUSAN_SIDO
        && GU_EXACT.has(r.geo) && !state.gu.has(r.district)) return false;

    for (const g of GROUPS) {
      const picked = effective[g.key];
      if (g.key === "region" && NATIONWIDE_GEO.has(r.geo)) continue;
      if (g.buckets) {
        const b = termBucket(r.term);
        if (!b || !picked.has(b.id)) return false;
        continue;
      }
      if (!picked.has(String(r[g.key]))) return false;
    }

    const prefNarrowed = state.prefTags.size > 0
      && state.prefTags.size < PREF_TAG_CODES.length;
    if (prefNarrowed) {
      if (!r.prefTags || !r.prefTags.size) return false;
      let hit = false;
      state.prefTags.forEach((code) => { if (r.prefTags.has(code)) hit = true; });
      if (!hit) return false;
    }
    if (state.dfrom != null && !(r.asOf && r.asOf >= state.dfrom)) return false;
    if (state.dto != null && !(r.asOf && r.asOf <= state.dto)) return false;
    if (state.hideZero && isShownAsZero(rateOf(r))) return false;
    if (state.rmin != null && !(rateOf(r) >= state.rmin)) return false;

    const tmin = presetOwnValue(p, "tmin");
    const tmax = presetOwnValue(p, "tmax");
    if (tmin != null && !(r.term >= tmin)) return false;
    if (tmax != null && !(r.term <= tmax)) return false;
    if (state.q) {
      const hay = `${r.institution} ${r.product} ${r.region || ""} ${r.district || ""}`;
      if (!hay.toLowerCase().includes(state.q)) return false;
    }
    return true;
  };

  const presetOn = (p) => {
    const picksOn = Object.entries(p.pick).every(([k, vs]) =>
      state.picked[k].size === vs.length && vs.every((v) => state.picked[k].has(v)));
    const valuesOn = Object.entries(p.values || {}).every(([k, v]) => state[k] === v);
    return picksOn && valuesOn;
  };

  const renderPresets = () => {
    $("presets").innerHTML = COND_PRESETS.map((p) => {
      const n = ALL.length ? ALL.filter((r) => rowMatchesPreset(r, p)).length : null;
      return `<button type="button" data-preset="${esc(p.id)}"`
        + (p.business ? ' data-business="1"' : "")
        + ` aria-pressed="${presetOn(p)}">${esc(p.label)}`
        + (n == null ? "" : `<span class="n">${num(n)}</span>`) + `</button>`;
    }).join("");
  };

  $("presets").addEventListener("click", (e) => {
    const b = e.target.closest("[data-preset]");
    if (!b) return;
    const p = COND_PRESETS.find((x) => x.id === b.dataset.preset);
    if (!p) return;
    const on = presetOn(p);
    Object.entries(p.pick).forEach(([k, vs]) => {
      const g = GROUPS.find((x) => x.key === k);
      state.picked[k].clear();
      if (on && g) applyDefaultGroup(g);
      else vs.forEach((v) => state.picked[k].add(v));
    });
    Object.entries(p.values || {}).forEach(([k, v]) => {
      state[k] = on ? PRESET_VALUE_DEFAULTS[k] : v;
    });
    // scalar state는 checkbox render로 갱신되지 않으므로 입력칸도 같은 tick에
    // 동기화한다. URL/버튼/실제 결과가 서로 다른 숨은 상태를 만들지 않는다.
    $("tmin").value = state.tmin == null ? "" : String(state.tmin);
    $("tmax").value = state.tmax == null ? "" : String(state.tmax);

    // 우대조건·부산을 끄면 그 아래 조건도 함께 비운다. 체크박스 쪽과 같은
    // 규칙이다 — 부산을 껐는데 구·군만 남으면 아무것도 안 걸린 것처럼 보인다.
    if (!state.picked.prefStatus.has("present")) {
      state.prefTags.clear(); state.detailOpen.delete("pref");
    } else if (!state.prefTags.size) selectAllPreferenceTags();
    if (!busanOn()) {
      state.gu.clear(); state.detailOpen.delete("gu");
    } else if (!state.gu.size) selectAllBusanDistricts();
    renderGroups();
    renderPresets();
    redraw();
  });

'''

text = PATH.read_text(encoding="utf-8")
start = text.find(START)
end = text.find(END)
if start < 0 or end < 0 or end <= start:
    raise SystemExit("preset block anchors not found")
if text.count(START) != 1 or text.count(END) != 1:
    raise SystemExit("preset block anchors are not unique")
PATH.write_text(text[:start] + NEW + text[end:], encoding="utf-8")
print("patched", PATH)
