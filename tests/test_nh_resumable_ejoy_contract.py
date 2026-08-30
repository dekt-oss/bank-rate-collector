from decimal import Decimal

from rate_monitor.collectors.nh_local import parser
from rate_monitor.collectors.nh_local.resumable import (
    NH_ACQUISITION_CONTRACT_VERSION,
    NhResumableAdapter,
)
from rate_monitor.domain.enums import ProductType
from rate_monitor.domain.schemas import RawArtifactData


def _artifact(screen: str, product: ProductType, body: str) -> RawArtifactData:
    return RawArtifactData(
        artifact_type="html",
        content=body.encode(),
        filename=f"{screen}.html",
        request_meta={
            "kind": "rate",
            "screen": screen,
            "product_type": product.value,
            "as_of": "2026-08-30",
            "outlet": {
                "brc": "123456",
                "name": "테스트농협",
                "address": "부산광역시 테스트구",
            },
        },
        schema_fingerprint="fixture",
        source_role="secondary_official",
        trust_level="official_direct",
    )


EJOY_NOTE_HTML = (
    "- 대상예금 &lt;거치식&gt; 정기예탁금, 복리식 정기예탁금 "
    "&lt;적립식&gt; 정기적금, 자유적립 적금, 자유로 부금 "
    "- 상품별 금리 + 우대금리 적용"
)


def _table(*rows: str) -> str:
    return "<table><caption>금리 상세정보</caption><tbody>" + "".join(rows) + "</tbody></table>"


def _row(product: str, term: str, rate: str, note: str = "기준", interest: str = "고정금리") -> str:
    return (
        f"<tr><td>{product}</td><td>{term}</td><td>{rate}</td>"
        f"<td>{note}</td><td>{interest}</td></tr>"
    )


def test_resumable_v2_rebuilds_ejoy_metadata_for_same_brc_term_and_savings() -> None:
    term = _artifact(
        parser.SCREEN_BY_PRODUCT[ProductType.TERM_DEPOSIT],
        ProductType.TERM_DEPOSIT,
        _table(
            _row("정기예탁금", "12개월 이상~24개월 미만", "3.0%"),
            _row(
                parser.EJOY_PRODUCT_NAME,
                "12개월 이상~24개월 미만",
                "0.2%",
                EJOY_NOTE_HTML,
            ),
        ),
    )
    savings = _artifact(
        parser.SCREEN_BY_PRODUCT[ProductType.INSTALLMENT_SAVINGS],
        ProductType.INSTALLMENT_SAVINGS,
        _table(_row("정기적금", "12개월 이상~24개월 미만", "3.1%")),
    )

    enriched = NhResumableAdapter._attach_ejoy_metadata([term, savings])
    assert enriched[0].content == term.content
    assert enriched[1].content == savings.content
    assert enriched[0].request_meta["ejoy_options"] == enriched[1].request_meta["ejoy_options"]
    assert enriched[0].request_meta["ejoy_options"][0]["add_rate"] == "0.2"

    outlet = parser.NhOutlet("123456", "테스트농협", "부산광역시 테스트구")
    term_rows, _ = parser.parse_detail(
        term.content.decode(),
        outlet=outlet,
        product_type=ProductType.TERM_DEPOSIT,
        as_of=__import__('datetime').date(2026, 8, 30),
        ejoy_options=enriched[0].request_meta["ejoy_options"],
    )
    savings_rows, _ = parser.parse_detail(
        savings.content.decode(),
        outlet=outlet,
        product_type=ProductType.INSTALLMENT_SAVINGS,
        as_of=__import__('datetime').date(2026, 8, 30),
        ejoy_options=enriched[1].request_meta["ejoy_options"],
    )
    assert any(row.max_rate == Decimal("3.2") for row in term_rows)
    assert any(row.max_rate == Decimal("3.3") for row in savings_rows)


def test_resumable_without_term_evidence_stays_fail_closed() -> None:
    savings = _artifact(
        parser.SCREEN_BY_PRODUCT[ProductType.INSTALLMENT_SAVINGS],
        ProductType.INSTALLMENT_SAVINGS,
        _table(_row("정기적금", "12개월 이상~24개월 미만", "3.1%")),
    )
    enriched = NhResumableAdapter._attach_ejoy_metadata([savings])
    assert enriched[0].request_meta["ejoy_options"] == []


def test_resumable_contract_version_bumped_for_ejoy_metadata_contract() -> None:
    assert NH_ACQUISITION_CONTRACT_VERSION == 2


def test_resumable_plan_forces_term_before_savings() -> None:
    adapter = object.__new__(NhResumableAdapter)
    outlet = parser.NhOutlet("123456", "테스트농협", "부산광역시 테스트구")
    plan = adapter._build_plan(
        [outlet],
        (ProductType.INSTALLMENT_SAVINGS, ProductType.TERM_DEPOSIT),
    )
    assert [item["product"] for item in plan] == [
        ProductType.TERM_DEPOSIT,
        ProductType.INSTALLMENT_SAVINGS,
    ]
