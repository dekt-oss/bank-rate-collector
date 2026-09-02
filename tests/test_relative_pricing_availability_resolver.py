import sqlite3
from pathlib import Path

import pytest

from rate_monitor.services.fsb_availability_service import availability_match_key
from rate_monitor.services.relative_pricing_availability_resolver import (
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNRESOLVED,
    resolve_fsb_relative_pricing_availability,
)


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE institution_availability_memberships (
                source_id TEXT NOT NULL,
                institution_id TEXT NOT NULL,
                product_type TEXT NOT NULL,
                area_code TEXT NOT NULL,
                availability_match_key TEXT NOT NULL,
                source_effective_date TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert(
    path: Path,
    institution_id: str,
    area_code: str,
    *,
    valid_from: str = "2026-09-01 00:00:00",
    valid_to: str | None = None,
    source_effective_date: str = "2026-09-01",
    match_key: str | None = None,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO institution_availability_memberships(
                source_id, institution_id, product_type, area_code,
                availability_match_key, source_effective_date, valid_from, valid_to
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "fsb",
                institution_id,
                "term_deposit",
                area_code,
                match_key or availability_match_key(area_code),
                source_effective_date,
                valid_from,
                valid_to,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_missing_membership_table_fails_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    sqlite3.connect(db_path).close()

    result = resolve_fsb_relative_pricing_availability(
        db_path, anchor_institution_id="our-bank"
    )

    assert result.status == RESOLUTION_UNRESOLVED
    assert result.reason == "availability_membership_table_unavailable"
    assert result.availability_match_key is None
    assert result.cohort_institution_ids == ()


def test_no_active_anchor_membership_stays_unresolved(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)
    _insert(db_path, "peer-a", "YN_Busan")

    result = resolve_fsb_relative_pricing_availability(
        db_path, anchor_institution_id="our-bank"
    )

    assert result.status == RESOLUTION_UNRESOLVED
    assert result.reason == "availability_match_key_unresolved"
    assert result.active_match_keys == ()


def test_single_active_membership_resolves_exact_area_cohort(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)
    _insert(db_path, "our-bank", "YN_Busan")
    _insert(db_path, "peer-b", "YN_Busan")
    _insert(db_path, "peer-a", "YN_Busan")
    _insert(db_path, "seoul-only", "YN_Seoul")

    result = resolve_fsb_relative_pricing_availability(
        db_path, anchor_institution_id="our-bank"
    )

    expected = availability_match_key("YN_Busan")
    assert result.status == RESOLUTION_RESOLVED
    assert result.reason is None
    assert result.availability_match_key == expected
    assert result.active_match_keys == (expected,)
    assert result.cohort_institution_ids == ("our-bank", "peer-a", "peer-b")


def test_multiple_active_memberships_fail_closed_as_ambiguous(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)
    _insert(db_path, "our-bank", "YN_Busan")
    _insert(db_path, "our-bank", "YN_Seoul")

    result = resolve_fsb_relative_pricing_availability(
        db_path, anchor_institution_id="our-bank"
    )

    assert result.status == RESOLUTION_AMBIGUOUS
    assert result.reason == "availability_match_key_ambiguous"
    assert result.availability_match_key is None
    assert result.active_match_keys == tuple(
        sorted(
            (
                availability_match_key("YN_Busan"),
                availability_match_key("YN_Seoul"),
            )
        )
    )
    assert result.cohort_institution_ids == ()


def test_historical_as_of_does_not_carry_current_membership_backward(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)
    _insert(
        db_path,
        "our-bank",
        "YN_Busan",
        valid_from="2026-08-01 00:00:00",
        valid_to="2026-08-20 00:00:00",
        source_effective_date="2026-08-01",
    )
    _insert(
        db_path,
        "our-bank",
        "YN_Seoul",
        valid_from="2026-09-01 00:00:00",
        source_effective_date="2026-09-01",
    )
    _insert(
        db_path,
        "peer-old",
        "YN_Busan",
        valid_from="2026-08-01 00:00:00",
        valid_to="2026-08-20 00:00:00",
        source_effective_date="2026-08-01",
    )

    historical = resolve_fsb_relative_pricing_availability(
        db_path,
        anchor_institution_id="our-bank",
        as_of="2026-08-10 12:00:00",
    )
    gap = resolve_fsb_relative_pricing_availability(
        db_path,
        anchor_institution_id="our-bank",
        as_of="2026-08-25 12:00:00",
    )

    assert historical.status == RESOLUTION_RESOLVED
    assert historical.availability_match_key == availability_match_key("YN_Busan")
    assert historical.cohort_institution_ids == ("our-bank", "peer-old")
    assert gap.status == RESOLUTION_UNRESOLVED
    assert gap.reason == "availability_match_key_unresolved"


def test_corrupted_persisted_match_key_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)
    _insert(
        db_path,
        "our-bank",
        "YN_Busan",
        match_key="fsb:term_deposit:area:YN_Seoul",
    )

    with pytest.raises(ValueError, match="does not match authoritative AREA"):
        resolve_fsb_relative_pricing_availability(
            db_path, anchor_institution_id="our-bank"
        )
