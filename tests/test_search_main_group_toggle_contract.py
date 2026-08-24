from __future__ import annotations

from pathlib import Path

TEMPLATE = Path("web/templates/site.html")


def _text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_main_group_empty_is_render_gate_not_matcher_rewrite() -> None:
    text = _text()

    assert "const emptyMainGroup = () =>" in text
    assert "const emptyGroup = emptyMainGroup();" in text
    assert "renderMainGroupEmpty(emptyGroup);" in text

    # D0/D1 must not reinterpret the canonical matcher. Empty main groups are
    # blocked at render entry so chart/table/rank/reference all share one state.
    assert "if (!picked.size) continue;" in text


def test_main_group_last_checkbox_no_longer_auto_recovers() -> None:
    text = _text()

    assert "if (!set.size) selectAllGroup(box.dataset.group);" not in text
    assert "syncGroupToggleButton(key);" in text
    assert 'allSelected ? "전체 해제" : "전체 선택"' in text
    assert 'button.setAttribute("aria-pressed", String(allSelected));' in text


def test_explicit_empty_round_trips_through_url() -> None:
    text = _text()

    assert 'p.set(k, v.join(","));' in text
    assert "if (p.has(k)) urlSetKeys.add(k);" in text
    assert "GROUPS.filter((g) => !urlSetKeys.has(g.key)).forEach(applyDefaultGroup);" in text


def test_empty_state_clears_outputs_and_has_inline_recovery() -> None:
    text = _text()

    assert '$("count").textContent = "0건";' in text
    assert 'data-recover-group="${esc(g.key)}"' in text
    assert '$("hist").innerHTML = "";' in text
    assert '$("terms").innerHTML = "";' in text
    assert '$("reg").innerHTML = "";' in text
    assert '$("marks").innerHTML = `<div class="mark">' in text


def test_nested_group_all_actions_remain_select_only() -> None:
    text = _text()

    # D1 deliberately excludes 부산 구·군 and detailed preference tags. Their
    # existing "전체 선택" behavior stays select-only until the 4-state D1b work.
    assert 'data-all="gu">전체 선택</button>' in text
    assert 'data-all="prefTags">전체 선택</button>' in text
    assert 'if (key === "gu") {\n        selectAllBusanDistricts();' in text
    assert 'else if (key === "prefTags") {\n        selectAllPreferenceTags();' in text
