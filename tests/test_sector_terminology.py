from pathlib import Path


def _template() -> str:
    return Path("web/templates/site.html").read_text(encoding="utf-8")


def test_sector_filter_and_column_use_industry_term() -> None:
    html = _template()
    assert '{ key: "sector", label: "업권", ko: SECTOR_KO }' in html
    assert '{ key: "sector", label: "업권", cell:' in html
    assert '{ key: "sector", label: "권역"' not in html


def test_geographic_region_wording_is_preserved() -> None:
    html = _template()
    # 지리적 지역 묶음은 여전히 권역이다. P1-5는 sector 명칭만 바꾼다.
    assert "권역별" in html
