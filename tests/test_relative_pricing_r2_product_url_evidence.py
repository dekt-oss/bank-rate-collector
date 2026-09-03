from scripts.relative_pricing_r2_product_url_evidence import (
    approved_product_url,
    has_12m_rate,
    page_signal_evidence,
    product_key,
    visible_html_text,
)


def _row(**overrides):
    row = {
        "FINAN_COMP_CODE": "0013002",
        "FINAN_PROD_CODE": "BNK1003",
        "URL": "http://www.bnksb.com/",
        "PRODUCT_URL": "https://www.bnksb.com/sub.do?code=02_prod0104",
        "TOP_12M_DAN": "3.80",
    }
    row.update(overrides)
    return row


def test_exact_product_key_and_12m_rate_scope() -> None:
    assert product_key(_row()) == "0013002:BNK1003"
    assert has_12m_rate(_row()) is True
    assert has_12m_rate(_row(TOP_12M_DAN="", TOP_6M_DAN="3.80")) is False


def test_product_url_must_match_official_bank_host() -> None:
    url, status = approved_product_url(_row())
    assert url == "https://www.bnksb.com/sub.do?code=02_prod0104"
    assert status == "approved_https"

    rejected, reason = approved_product_url(
        _row(PRODUCT_URL="https://attacker.example/product")
    )
    assert rejected is None
    assert reason == "product_bank_host_mismatch"


def test_http_product_url_is_only_probed_via_https() -> None:
    url, status = approved_product_url(
        _row(PRODUCT_URL="http://bnksb.com/product")
    )
    assert url == "https://bnksb.com/product"
    assert status == "http_upgraded_to_https"


def test_fsb_hosted_product_disclosure_is_allowed() -> None:
    url, status = approved_product_url(
        _row(PRODUCT_URL="https://choeunbank.ibs.fsb.or.kr/ProdList_001.act?rnum=1")
    )
    assert url is not None
    assert status == "approved_https"


def test_page_text_signal_never_becomes_historical_classification() -> None:
    result = page_signal_evidence("정기예금 특판 판매종료")
    assert result["positive_special_signals"] == ["특판", "판매종료"]
    assert result["historical_as_of_proven"] is False
    assert result["absence_means_normal"] is False

    no_signal = page_signal_evidence("일반 정기예금 상품 안내")
    assert no_signal["positive_special_signals"] == []
    assert no_signal["absence_means_normal"] is False


def test_only_visible_html_text_is_classified() -> None:
    text = visible_html_text(
        "<style>.특판{color:red}</style><script>const x='특판'</script>"
        "<main>일반 정기예금</main>"
    )
    assert "특판" not in text
    assert page_signal_evidence(text)["positive_special_signals"] == []
