"""P0-3 농·축협 interest_method data migration 회귀 테스트."""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.identifiers import make_variant_key

REPO_ROOT = Path(__file__).resolve().parents[1]
OLD_REVISION = "f2c90d8e7a11"


def _alembic(command: str, db_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *command.split()],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "RATE_MONITOR_DB_URL": f"sqlite+pysqlite:///{db_path}",
            "PYTHONPATH": str(REPO_ROOT / "src"),
        },
        capture_output=True,
        text=True,
    )


def _variant_key(product: str, method: str) -> str:
    return make_variant_key(
        sector="nh_local",
        org_key="nh_local:333072",
        source_product_key=product,
        product_name=product,
        term_months=12,
        term_days=None,
        join_channel="unknown",
        interest_method=method,
        payment_method=None,
        amount_min=None,
        amount_max=None,
        outlet_key="333072",
    )


def _seed(db_path: Path, *, collision: bool = False) -> dict[str, str]:
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 10, 19, 0, 0)

    with session_scope(factory) as session:
        source = m.Source(
            id="nh_local",
            name="농협 금융상품몰 농·축협별 예금금리",
            sector="nh_local",
            mode="http",
            source_role="secondary_official",
            trust_level="official_direct",
            priority=10,
            enabled=True,
            policy_status="allowed",
            coverage_status="partial",
            parser_version="0.1.0",
            created_at=now,
            updated_at=now,
        )
        institution = m.Institution(
            sector="nh_local",
            canonical_name="강릉농협 강동지점",
            normalized_name="강릉농협강동지점",
            geo_basis="outlet_address",
            geo_confidence="high",
            address="강원특별자치도 강릉시 강동면 와천로 463",
            availability_scope="unknown",
            active=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add_all([source, institution])
        session.flush()

        outlet = m.Outlet(
            institution_id=institution.id,
            name="강릉농협 강동지점",
            geo_basis="outlet_address",
            geo_confidence="high",
            address=institution.address,
            active=True,
        )
        session.add(outlet)
        session.flush()
        session.add(
            m.SourceEntityLink(
                source_id="nh_local",
                entity_type="outlet",
                source_entity_key=f"{institution.id}:333072",
                entity_id=outlet.id,
                source_name=outlet.name,
                confidence=1.0,
                match_method="exact_code",
                valid_from=now.date(),
                valid_to=None,
                created_at=now,
                updated_at=now,
            )
        )

        products = {}
        for name in (
            "정기예탁금",
            "e-joy 인터넷예금 우대금리",
            "복리식정기예탁금",
        ):
            product = m.Product(
                institution_id=institution.id,
                product_type="term_deposit",
                name=name,
                normalized_name=name,
                active=True,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(product)
            session.flush()
            products[name] = product

        methods = {
            "정기예탁금": "simple",
            "e-joy 인터넷예금 우대금리": "compound",
            "복리식정기예탁금": "compound",
        }
        ids = {}
        for name, method in methods.items():
            variant = m.ProductVariant(
                product_id=products[name].id,
                outlet_id=outlet.id,
                term_months=12,
                term_days=None,
                join_channel="unknown",
                interest_method=method,
                payment_method=None,
                amount_min=None,
                amount_max=None,
                customer_scope=None,
                rate_scope="outlet",
                variant_key=_variant_key(name, method),
            )
            session.add(variant)
            session.flush()
            ids[name] = variant.id

        if collision:
            session.add(
                m.ProductVariant(
                    product_id=products["정기예탁금"].id,
                    outlet_id=outlet.id,
                    term_months=12,
                    term_days=None,
                    join_channel="unknown",
                    interest_method="unknown",
                    payment_method=None,
                    amount_min=None,
                    amount_max=None,
                    customer_scope=None,
                    rate_scope="outlet",
                    variant_key=_variant_key("정기예탁금", "unknown"),
                )
            )

    return ids


def test_migration_reclassifies_only_inferred_nh_methods(tmp_path: Path) -> None:
    db_path = tmp_path / "interest.sqlite3"
    before = _alembic(f"upgrade {OLD_REVISION}", db_path)
    assert before.returncode == 0, before.stderr
    ids = _seed(db_path)

    result = _alembic("upgrade head", db_path)
    assert result.returncode == 0, result.stderr

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        rows = {
            row.id: row
            for row in session.scalars(select(m.ProductVariant)).all()
        }
        plain = rows[ids["정기예탁금"]]
        bonus = rows[ids["e-joy 인터넷예금 우대금리"]]
        compound = rows[ids["복리식정기예탁금"]]

        assert plain.interest_method == "unknown"
        assert plain.variant_key == _variant_key("정기예탁금", "unknown")
        assert bonus.interest_method == "unknown"
        assert bonus.variant_key == _variant_key("e-joy 인터넷예금 우대금리", "unknown")
        assert compound.interest_method == "compound"
        assert compound.variant_key == _variant_key("복리식정기예탁금", "compound")


def test_migration_fails_closed_on_target_variant_collision(tmp_path: Path) -> None:
    db_path = tmp_path / "collision.sqlite3"
    before = _alembic(f"upgrade {OLD_REVISION}", db_path)
    assert before.returncode == 0, before.stderr
    _seed(db_path, collision=True)

    result = _alembic("upgrade head", db_path)
    assert result.returncode != 0
    assert "target variant_key" in result.stderr
