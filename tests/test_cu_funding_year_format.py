import pytest

from rate_monitor.collectors.cu.funding import select_latest_disclosures


def _row(name: str) -> dict[str, object]:
    return {
        "cuIngno": "02022",
        "disclosureNo": 18387,
        "disclosureTy": "2",
        "disclosureName": name,
        "regDate": "2024-08-01",
        "shortFileName": "summary.pdf",
        "bogoTy": "Y",
        "chkYn3": "Y",
    }


@pytest.mark.parametrize(
    "name",
    [
        "2024년도 상반기결산공시",
        "2024년 상반기결산공시",
        "2024회계연도 정기공시",
        "2024상반기경영공시",
    ],
)
def test_cu_disclosure_year_accepts_observed_official_formats(name: str) -> None:
    selected = select_latest_disclosures([_row(name)], cu_ingno="02022", periods=1)

    assert len(selected) == 1
    assert selected[0].source_effective_month == "2024-06"
    assert selected[0].disclosure_no == 18387
