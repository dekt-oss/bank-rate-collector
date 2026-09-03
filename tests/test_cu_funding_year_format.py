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


def test_cu_disclosure_year_ignores_only_older_unlabeled_history() -> None:
    newer = _row("2024년도 상반기결산공시")
    newer["disclosureNo"] = 18387
    newer["regDate"] = "2024-08-01"
    older = _row("상반기결산공시")
    older["disclosureNo"] = 7658
    older["regDate"] = "2021-09-09"

    selected = select_latest_disclosures(
        [newer, older],
        cu_ingno="02022",
        periods=12,
    )

    assert [item.disclosure_no for item in selected] == [18387]
