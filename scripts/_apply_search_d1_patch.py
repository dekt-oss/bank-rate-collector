from __future__ import annotations

from pathlib import Path

PATH = Path("web/templates/site.html")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


text = PATH.read_text(encoding="utf-8")

text = replace_once(
    text,
    '''  const groupValues = (g) => g.buckets
    ? g.buckets.map((b) => b.id)
    : [...countsOf(g.key).keys()].map(String);
''',
    '''  const groupValues = (g) => g.buckets
    ? g.buckets.map((b) => b.id)
    : [...countsOf(g.key).keys()].map(String);
  const groupAllSelected = (g) => {
    const all = groupValues(g);
    const picked = state.picked[g.key];
    return all.length > 0 && picked.size === all.length
      && all.every((v) => picked.has(v));
  };
  const emptyMainGroup = () =>
    GROUPS.find((g) => state.picked[g.key].size === 0) || null;
''',
    "main group state helpers",
)

text = replace_once(
    text,
    '''  const shortGroupSummary = (key) => {
    const g = GROUPS.find((x) => x.key === key);
    const picked = state.picked[key];
    const all = groupValues(g);
    if (all.length && all.every((v) => picked.has(v))) return `${g.label} 전체`;
    if (g.buckets) return [...picked]
      .map((v) => (g.buckets.find((b) => b.id === v) || {}).label || v).join(" · ");
    return [...picked].map((v) => g.ko ? (g.ko[v] || v) : v).join(" · ") || `${g.label} 전체`;
  };
''',
    '''  const shortGroupSummary = (key) => {
    const g = GROUPS.find((x) => x.key === key);
    const picked = state.picked[key];
    const all = groupValues(g);
    if (!picked.size) return `${g.label} 선택 없음`;
    if (all.length && all.every((v) => picked.has(v))) return `${g.label} 전체`;
    if (g.buckets) return [...picked]
      .map((v) => (g.buckets.find((b) => b.id === v) || {}).label || v).join(" · ");
    return [...picked].map((v) => g.ko ? (g.ko[v] || v) : v).join(" · ");
  };
''',
    "empty group summary",
)

text = replace_once(
    text,
    '''      return `<div class="group">
        <div class="lbl">${esc(g.label)}
          <button type="button" data-all="${esc(g.key)}">전체 선택</button>
        </div>
''',
    '''      const allSelected = groupAllSelected(g);
      return `<div class="group">
        <div class="lbl">${esc(g.label)}
          <button type="button" data-all="${esc(g.key)}"
                  aria-pressed="${allSelected}">${allSelected ? "전체 해제" : "전체 선택"}</button>
        </div>
''',
    "main group toggle button",
)

text = replace_once(
    text,
    '''  const renderGroups = () => {
    $("groups-basic").innerHTML = groupHtml(GROUPS.filter((g) => !g.advanced));
    $("groups-advanced").innerHTML = groupHtml(GROUPS.filter((g) => g.advanced));
    renderFilterSummary();
  };
''',
    '''  const renderGroups = () => {
    $("groups-basic").innerHTML = groupHtml(GROUPS.filter((g) => !g.advanced));
    $("groups-advanced").innerHTML = groupHtml(GROUPS.filter((g) => g.advanced));
    renderFilterSummary();
  };
  const syncGroupToggleButton = (key) => {
    const g = GROUPS.find((x) => x.key === key);
    if (!g) return;
    const button = [...document.querySelectorAll("#conditions [data-all]")]
      .find((el) => el.dataset.all === key);
    if (!button) return;
    const allSelected = groupAllSelected(g);
    button.textContent = allSelected ? "전체 해제" : "전체 선택";
    button.setAttribute("aria-pressed", String(allSelected));
  };
''',
    "toggle button sync helper",
)

text = replace_once(
    text,
    '''  const render = () => {
    renderFilterSummary();
    // 조건이 바뀌었으니 캐시부터 비운다. `current`를 새로 만들기 전에
    // 비워야, 아래에서 누가 물어도 옛 집합이 안 나온다.
    clearBasis();
    // `ALL.filter(matches)`로 쓰면 안 된다. `filter`가 두 번째 인자로
''',
    '''  const renderMainGroupEmpty = (g) => {
    current = [];
    $("count").textContent = "0건";
    $("note").textContent = "";
    renderAvg();

    const rank = $("rankline");
    rank.hidden = false;
    rank.className = "rankline off";
    rank.textContent = `${g.label} 선택 없음 — 전체 선택하면 순위와 격차가 표시됩니다`;

    $("rows").innerHTML = `<tr><td class="empty" colspan="${COLS.length}">`
      + `${esc(g.label)}이(가) 선택되지 않아 조회 결과가 없습니다. `
      + `<button type="button" class="act" data-recover-group="${esc(g.key)}">전체 선택</button>`
      + `</td></tr>`;
    $("more-wrap").hidden = true;
    renderHead();

    $("marks").hidden = false;
    $("marks").innerHTML = `<div class="mark"><div class="t">조회 조건</div>`
      + `<div class="v mute">0건</div><div class="d">${esc(g.label)} 선택 없음 · `
      + `전체 선택으로 복구할 수 있습니다.</div></div>`;

    $("charts").hidden = false;
    $("hist-badge").textContent = "조회 조건 없음";
    $("hist-badge").className = "badge";
    $("hist").innerHTML = "";
    $("hist").dataset.total = "0";
    $("hist").setAttribute("aria-label", `${g.label} 선택 없음`);
    $("hist-cap").textContent = `${g.label}이(가) 선택되지 않아 분포를 그리지 않습니다.`;
    $("hist-hover").textContent = "";
    $("hist-legend").innerHTML = "";

    $("terms-badge").textContent = "조회 조건 없음";
    $("terms-badge").className = "badge";
    $("terms").innerHTML = "";
    $("terms").setAttribute("aria-label", `${g.label} 선택 없음`);
    $("terms-cap").textContent = `${g.label}이(가) 선택되지 않아 기간별 범위를 그리지 않습니다.`;

    $("reg-title").textContent = "권역별 최고금리 중앙값";
    $("reg-cap").textContent = `${g.label}이(가) 선택되지 않아 권역 비교를 그리지 않습니다.`;
    $("reg").classList.remove("main-korea-map");
    $("reg").style.gridTemplateColumns = "";
    $("reg").innerHTML = "";
    $("reg").setAttribute("aria-label", `${g.label} 선택 없음`);
    $("reg-legend").innerHTML = "";
    syncUrl();
  };

  const render = () => {
    renderFilterSummary();
    // 조건이 바뀌었으니 캐시부터 비운다. `current`를 새로 만들기 전에
    // 비워야, 아래에서 누가 물어도 옛 집합이 안 나온다.
    clearBasis();
    // main group의 빈 선택은 «전체»가 아니라 명시적인 0건이다. matcher의
    // 기존 `!picked.size` 의미는 건드리지 않고 render 진입점에서만 차단한다.
    const emptyGroup = emptyMainGroup();
    if (emptyGroup) {
      renderMainGroupEmpty(emptyGroup);
      return;
    }
    // `ALL.filter(matches)`로 쓰면 안 된다. `filter`가 두 번째 인자로
''',
    "render entry empty gate",
)

text = replace_once(
    text,
    '''    URL_SETS.forEach((k) => {
      const v = [...state.picked[k]];
      if (v.length) p.set(k, v.join(","));
    });
''',
    '''    URL_SETS.forEach((k) => {
      const v = [...state.picked[k]];
      // 빈 main group도 `key=`로 명시한다. 생략하면 reload에서 default가
      // 다시 채워져 «선택 없음» 링크가 «전체 선택» 링크로 바뀐다.
      p.set(k, v.join(","));
    });
''',
    "explicit empty URL state",
)

text = replace_once(
    text,
    '''    const set = state.picked[box.dataset.group];
    if (box.checked) set.add(box.value); else set.delete(box.value);
    // 마지막 하나를 끄면 다시 전체 선택으로 돌린다. 빈 체크를 «전체»로
    // 해석하면 화면과 실제 조건이 반대로 보이기 때문이다.
    if (!set.size) selectAllGroup(box.dataset.group);
    // 부산을 끄면 구·군도 함께 비운다. 안 비우면 안 보이는 조건이 살아
''',
    '''    const key = box.dataset.group;
    const set = state.picked[key];
    if (box.checked) set.add(box.value); else set.delete(box.value);
    // main group은 마지막 하나까지 실제로 끌 수 있다. 0개는 render 진입
    // gate가 0건으로 처리하므로, 내부 state를 몰래 전체 선택으로 되돌리지 않는다.
    // 부산을 끄면 구·군도 함께 비운다. 안 비우면 안 보이는 조건이 살아
''',
    "remove last-checkbox auto recovery",
)

text = replace_once(
    text,
    '''    if (box.dataset.group === "region") {
      if (!busanOn()) {
        state.gu.clear(); state.detailOpen.delete("gu");
      } else if (!state.gu.size) selectAllBusanDistricts();
      renderGroups();
    }
''',
    '''    if (key === "region") {
      if (!busanOn()) {
        state.gu.clear(); state.detailOpen.delete("gu");
      } else if (!state.gu.size) selectAllBusanDistricts();
      renderGroups();
    }
''',
    "region key local variable",
)

text = replace_once(
    text,
    '''    if (box.dataset.group === "prefStatus") {
      if (!state.picked.prefStatus.has("present")) {
        state.prefTags.clear(); state.detailOpen.delete("pref");
      } else if (!state.prefTags.size) selectAllPreferenceTags();
      renderGroups();
    }
    renderPresets();
''',
    '''    if (key === "prefStatus") {
      if (!state.picked.prefStatus.has("present")) {
        state.prefTags.clear(); state.detailOpen.delete("pref");
      } else if (!state.prefTags.size) selectAllPreferenceTags();
      renderGroups();
    }
    if (key !== "region" && key !== "prefStatus") syncGroupToggleButton(key);
    renderPresets();
''',
    "generic toggle button sync",
)

text = replace_once(
    text,
    '''      if (key === "gu") {
        selectAllBusanDistricts();
      } else if (key === "prefTags") {
        selectAllPreferenceTags();
      } else {
        selectAllGroup(key);
      }
''',
    '''      if (key === "gu") {
        selectAllBusanDistricts();
      } else if (key === "prefTags") {
        selectAllPreferenceTags();
      } else {
        const g = GROUPS.find((x) => x.key === key);
        if (g && groupAllSelected(g)) {
          state.picked[key].clear();
          if (key === "region") {
            state.gu.clear(); state.detailOpen.delete("gu");
          }
          if (key === "prefStatus") {
            state.prefTags.clear(); state.detailOpen.delete("pref");
          }
        } else {
          selectAllGroup(key);
        }
      }
''',
    "main group all toggle",
)

text = replace_once(
    text,
    '''  $("rows").addEventListener("click", (e) => {
    // 행 아무 데나 누르면 원문이 열리고, 다시 누르면 닫힌다. 펼친 원문
''',
    '''  $("rows").addEventListener("click", (e) => {
    const recover = e.target.closest("[data-recover-group]");
    if (recover) {
      selectAllGroup(recover.dataset.recoverGroup);
      renderGroups();
      renderPresets();
      redraw();
      return;
    }
    // 행 아무 데나 누르면 원문이 열리고, 다시 누르면 닫힌다. 펼친 원문
''',
    "inline empty recovery",
)

PATH.write_text(text, encoding="utf-8")
print("Search D1 template patch applied")
