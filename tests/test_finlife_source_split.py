"""finlife 소스 분리 (v4 §6.2, §6.5).

같은 API가 저축은행(`030300`)과 시중은행(`020000`)을 함께 준다. 하나의
`source_id`로 묶어 두면 화면이 둘을 못 가른다 — 시중은행은 참고지표로
내려가고 저축은행은 메인 비교표에 남아야 한다.

여기서 지키는 것은 **둘이 섞이지 않는다**는 것 하나다.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from rate_monitor.collectors.base import CollectorError
from rate_monitor.collectors.finlife import parser
from rate_monitor.collectors.finlife.adapter import (
    FinlifeBankAdapter,
    FinlifeSavingsBankAdapter,
)
from rate_monitor.domain.enums import RateScope, Sector
from rate_monitor.domain.schemas import CollectionRequest

FIXTURES = Path(__file__).parent / "fixtures" / "finlife"
DEPOSIT = FIXTURES / "deposit_savings_bank_page1.json"


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("FINLIFE_API_KEY", "test-key")


def _payload() -> dict:
    return json.loads(DEPOSIT.read_text(encoding="utf-8"))


# ── 파서 ────────────────────────────────────────────────────────────────


def test_the_row_names_its_own_source_from_the_group() -> None:
    """어댑터가 알려 주는 대신 응답의 권역코드로 정한다.

    그래야 어댑터 설정이 어긋나도 저축은행 행이 은행 소스로 들어가지 않는다.
    """
    rows, _ = parser.parse(_payload(), "depositProductsSearch", "030300")
    assert rows
    assert {r.source_id for r in rows} == {"finlife_savings_bank"}
    assert {r.sector for r in rows} == {Sector.SAVINGS_BANK}

    # 같은 원본을 은행 권역이라고 읽으면 은행 소스가 된다. 권역이 정한다.
    rows, _ = parser.parse(_payload(), "depositProductsSearch", "020000")
    assert {r.source_id for r in rows} == {"finlife_bank"}
    assert {r.sector for r in rows} == {Sector.BANK}


def test_the_bank_group_is_nationwide_and_the_savings_bank_group_is_not() -> None:
    """저축은행 공시는 본점 기준이라 지역 지점금리로 오해되면 안 된다."""
    bank, _ = parser.parse(_payload(), "depositProductsSearch", "020000")
    savings, _ = parser.parse(_payload(), "depositProductsSearch", "030300")
    assert {r.rate_scope for r in bank} == {RateScope.NATIONWIDE}
    assert {r.rate_scope for r in savings} == {RateScope.HEAD_OFFICE_REFERENCE}


def test_an_unknown_group_is_refused_not_guessed() -> None:
    """모르는 권역을 기본값으로 넘기면 그 행이 어느 원천인지 아무도 모른다."""
    from rate_monitor.collectors.base import ParseError

    with pytest.raises(ParseError, match="source_id를 정할 수 없는"):
        parser.parse(_payload(), "depositProductsSearch", "050000")


# ── 어댑터 ──────────────────────────────────────────────────────────────


def test_each_adapter_owns_one_group() -> None:
    """실행 하나가 소스 하나에 대응해야 실행 이력과 저장된 행이 맞물린다."""
    savings, bank = FinlifeSavingsBankAdapter(), FinlifeBankAdapter()
    assert (savings.source_id, savings.groups) == ("finlife_savings_bank", ("030300",))
    assert (bank.source_id, bank.groups) == ("finlife_bank", ("020000",))
    assert savings.sector == Sector.SAVINGS_BANK
    assert bank.sector == Sector.BANK


def test_an_adapter_refuses_a_group_it_does_not_own() -> None:
    """저축은행 어댑터로 은행을 받으면 실행 이력과 행의 source_id가 어긋난다."""
    import asyncio

    request = CollectionRequest(
        source_id="finlife_savings_bank", options={"groups": ("020000",)}
    )
    with pytest.raises(CollectorError, match="맡지 않은 권역"):
        asyncio.run(FinlifeSavingsBankAdapter().fetch(request))


def test_the_cli_no_longer_accepts_the_old_name() -> None:
    """`finlife` 하나로 돌리면 어느 권역인지 알 수 없다."""
    from rate_monitor.cli import ADAPTERS

    assert "finlife" not in ADAPTERS
    assert ADAPTERS["finlife_savings_bank"] is FinlifeSavingsBankAdapter
    assert ADAPTERS["finlife_bank"] is FinlifeBankAdapter


# ── 화면 ────────────────────────────────────────────────────────────────


def test_reference_sectors_come_from_the_config() -> None:
    """시중은행은 메인 비교표에 안 올린다 (v4 §6.4)."""
    from rate_monitor.services.dashboard_service import reference_sectors

    assert reference_sectors() == ("bank",)


def test_a_missing_config_hides_nothing(tmp_path) -> None:
    """설정이 없다고 화면이 조용히 비면 안 된다."""
    from rate_monitor.services.dashboard_service import reference_sectors

    assert reference_sectors(tmp_path / "없는파일.yaml") == ()


def test_db_only_sources_are_not_hidden_yet() -> None:
    """설정에 `finlife_savings_bank`가 적혀 있지만 아직 걸지 않는다.

    실측: finlife가 보는 저축은행 79곳 중 6곳(OK저축은행 등)이 FSB 수집분에
    없다. 지금 빼면 그 여섯이 화면에서 통째로 사라진다. 두 원천의 기관
    매핑이 생기는 v4 PR 7에서 건다.
    """
    import yaml

    from rate_monitor.services.dashboard_service import reference_sectors

    config = yaml.safe_load(Path("config/presentation.yaml").read_text(encoding="utf-8"))
    assert "finlife_savings_bank" in config["db_only_sources"]
    # 그런데 화면에서 빼는 것은 업권뿐이다.
    assert "finlife_savings_bank" not in reference_sectors()


def test_the_main_table_leaves_bank_rows_out(tmp_path) -> None:
    """참고지표가 2금융권 넷과 같은 표에 섞이면 안 된다."""
    from rate_monitor.services.dashboard_service import build_rate_table, latest_run_ids

    db = tmp_path / "t.sqlite3"
    _seed_two_sectors(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    table = build_rate_table(conn, latest_run_ids(conn))
    conn.close()

    sectors = table["lookups"]["sector"]
    assert "savings_bank" in sectors
    assert "bank" not in sectors


def _seed_two_sectors(db: Path) -> None:
    """저축은행 한 줄, 시중은행 한 줄을 심는다."""
    from datetime import UTC, datetime

    from rate_monitor.db import models as m
    from rate_monitor.db.session import create_db_engine, make_session_factory

    engine = create_db_engine(db)
    m.Base.metadata.create_all(engine)
    now = datetime.now(UTC).replace(tzinfo=None)
    factory = make_session_factory(engine)

    with factory() as s:
        for source_id, sector in (
            ("finlife_savings_bank", "savings_bank"),
            ("finlife_bank", "bank"),
        ):
            s.add(m.Source(
                id=source_id, name=source_id, sector=sector, mode="api",
                source_role="secondary_official", trust_level="official_direct",
                created_at=now, updated_at=now,
            ))
            s.add(m.CollectionRun(
                id=f"run-{sector}", source_id=source_id, mode="api",
                started_at=now, finished_at=now, status="success",
            ))
            s.add(m.RawArtifact(
                id=f"art-{sector}", run_id=f"run-{sector}", artifact_type="json",
                relative_path=f"{sector}.json", sha256=sector.ljust(64, "0"),
                content_length=1, captured_at=now,
            ))
            s.add(m.Institution(
                id=f"inst-{sector}", sector=sector, canonical_name=f"{sector} 은행",
                normalized_name=f"{sector}은행",
                first_seen_at=now, last_seen_at=now,
            ))
            s.add(m.Product(
                id=f"prod-{sector}", institution_id=f"inst-{sector}",
                name="정기예금", normalized_name="정기예금",
                product_type="term_deposit",
                first_seen_at=now, last_seen_at=now,
            ))
            s.add(m.ProductVariant(
                id=f"var-{sector}", product_id=f"prod-{sector}", term_months=12,
                rate_scope="nationwide", join_channel="unknown",
                interest_method="simple", variant_key=f"var-{sector}",
            ))
            s.add(m.RateObservation(
                id=f"obs-{sector}", variant_id=f"var-{sector}", run_id=f"run-{sector}",
                raw_artifact_id=f"art-{sector}", observed_at=now,
                base_rate="003.0000", base_source_locator=f"{sector}/0",
                source_record_hash=f"sha256:{sector}", validation_status="valid",
                content_hash=f"sha256:{sector}-content",
            ))
        s.commit()
