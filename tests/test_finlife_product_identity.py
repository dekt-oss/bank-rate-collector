"""FINLIFE deposit/saving 서비스 사이 상품코드 재사용 회귀 테스트."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scripts.finlife_identity_audit import audit_finlife_identity
from sqlalchemy import select

from rate_monitor.collectors.finlife.adapter import FinlifeSavingsBankAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.enums import ProductType, RunStatus
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.collection_service import collect_source


def _payload(product_name: str, *, saving: bool) -> bytes:
    option = {
        "fin_co_no": "0010001",
        "fin_prdt_cd": "240010",
        "save_trm": "12",
        "intr_rate_type": "S",
        "intr_rate_type_nm": "단리",
        "intr_rate": 3.0 if not saving else 2.5,
        "intr_rate2": 3.1 if not saving else 2.7,
    }
    if saving:
        option.update({"rsrv_type": "F", "rsrv_type_nm": "자유적립식"})
    return json.dumps(
        {
            "result": {
                "err_cd": "000",
                "baseList": [
                    {
                        "fin_co_no": "0010001",
                        "fin_prdt_cd": "240010",
                        "kor_co_nm": "충돌저축은행",
                        "fin_prdt_nm": product_name,
                        "join_way": "영업점",
                        "dcls_strt_day": "20260813",
                    }
                ],
                "optionList": [option],
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _artifact(service: str, product_name: str) -> RawArtifactData:
    saving = service == "savingProductsSearch"
    return RawArtifactData(
        artifact_type="json",
        content=_payload(product_name, saving=saving),
        filename=f"{service}_030300_page1.json",
        request_meta={
            "url": f"https://finlife.fss.or.kr/finlifeapi/{service}.json",
            "auth": "[REDACTED]",
            "service": service,
            "topFinGrpNo": "030300",
            "pageNo": 1,
        },
        schema_fingerprint=f"fp-{service}",
        source_role="secondary_official",
        trust_level="official_direct",
    )


class CollisionAdapter(FinlifeSavingsBankAdapter):
    def __init__(self) -> None:
        super().__init__(api_key="test-key")

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [
            _artifact("depositProductsSearch", "충돌 정기예금"),
            _artifact("savingProductsSearch", "충돌 정기적금"),
        ]


def test_same_finlife_code_in_two_services_stays_two_products(tmp_path: Path) -> None:
    db = tmp_path / "identity.sqlite3"
    raw_root = tmp_path / "raw"
    engine = create_db_engine(db)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    result = asyncio.run(
        collect_source(
            CollisionAdapter(),
            CollectionRequest(source_id="finlife_savings_bank"),
            factory,
            raw_root=raw_root,
        )
    )
    assert result.status == RunStatus.SUCCESS
    assert result.parsed_count == 2

    with factory() as session:
        products = session.scalars(select(m.Product).order_by(m.Product.product_type)).all()
        assert {(p.product_type, p.name) for p in products} == {
            (ProductType.TERM_DEPOSIT, "충돌 정기예금"),
            (ProductType.INSTALLMENT_SAVINGS, "충돌 정기적금"),
        }

        links = session.scalars(
            select(m.SourceEntityLink).where(m.SourceEntityLink.entity_type == "product")
        ).all()
        keys = {link.source_entity_key for link in links}
        assert any(key.endswith(":depositProductsSearch:240010") for key in keys)
        assert any(key.endswith(":savingProductsSearch:240010") for key in keys)

        observations = session.execute(
            select(m.Product.product_type, m.RawArtifact.relative_path)
            .join(m.ProductVariant, m.ProductVariant.product_id == m.Product.id)
            .join(m.RateObservation, m.RateObservation.variant_id == m.ProductVariant.id)
            .join(m.RawArtifact, m.RawArtifact.id == m.RateObservation.raw_artifact_id)
        ).all()
        assert len(observations) == 2
        for product_type, relative_path in observations:
            filename = Path(relative_path).name
            if filename.startswith("depositProductsSearch_"):
                assert product_type == ProductType.TERM_DEPOSIT
            elif filename.startswith("savingProductsSearch_"):
                assert product_type == ProductType.INSTALLMENT_SAVINGS
            else:  # pragma: no cover - test fixture contract
                raise AssertionError(f"unexpected raw artifact: {relative_path}")

    audit = audit_finlife_identity(db)
    assert audit["checked"] == 2
    assert audit["unknown_service"] == 0
    assert audit["mismatch_count"] == 0
