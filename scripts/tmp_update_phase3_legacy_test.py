from pathlib import Path

path = Path("tests/test_site_ui_v4.py")
text = path.read_text(encoding="utf-8")
old = '''    assert "const rowMatchesPick = (r, pick) =>" in SOURCE
    assert 'if (k === "region" && NATIONWIDE_GEO.has(r.geo)) return true;' in SOURCE
    # 표를 거를 때의 예외와 짝이다. 한쪽이 사라지면 둘이 어긋난다.
    assert 'if (g.key === "region" && NATIONWIDE_GEO.has(r.geo)) continue;' in SOURCE
    assert "ALL.filter((r) => rowMatchesPick(r, p.pick)).length" in SOURCE
'''
new = '''    assert "const rowMatchesPreset = (r, p) =>" in SOURCE
    # 프리셋 count도 실제 클릭 후 matcher와 같은 nationwide 예외를 사용한다.
    assert 'if (g.key === "region" && NATIONWIDE_GEO.has(r.geo)) continue;' in SOURCE
    assert "ALL.filter((r) => rowMatchesPreset(r, p)).length" in SOURCE
    # exact-12 preset은 bucket뿐 아니라 scalar range까지 count에 반영한다.
    assert 'const tmin = presetOwnValue(p, "tmin");' in SOURCE
    assert 'const tmax = presetOwnValue(p, "tmax");' in SOURCE
'''
if text.count(old) != 1:
    raise SystemExit("legacy preset assertion block not found exactly once")
path.write_text(text.replace(old, new), encoding="utf-8")
print("patched", path)
