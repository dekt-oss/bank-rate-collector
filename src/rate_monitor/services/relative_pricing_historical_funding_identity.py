"""Point-in-time identity resolution for savings-bank historical funding.

Funding observations contain mutable ``institution_id``/``identity_status`` fields:
operations such as savings-bank identity remediation may fill those fields after
the funding value was originally observed without creating a value revision.
Historical Relative Pricing must therefore not treat the current observation
identity as evidence that the mapping was known at an earlier cutoff.

This resolver reconstructs identity from source-link evidence that was recorded by
the requested cutoff. Direct Data.go exact-code+name links are accepted when they
already existed by the cutoff. Name-mismatch rows require the same FSB + Finlife
exact-code consensus as the production collector, with both reference links
recorded and effective by the cutoff. Current ``Institution.active`` is not used
because that mutable flag is not a historical activity record.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path

from rate_monitor.domain.identifiers import make_org_key

SAVINGS_BANK_SECTOR = "savings_bank"
DATA_GO_SAVINGS_BANK_SOURCE_ID = "data_go_savings_bank_funding"
FSB_SOURCE_ID = "fsb"
FINLIFE_SAVINGS_BANK_SOURCE_ID = "finlife_savings_bank"
REFERENCE_SOURCE_IDS = (FSB_SOURCE_ID, FINLIFE_SAVINGS_BANK_SOURCE_ID)
DIRECT_MATCH_METHODS = frozenset({"exact_fss_code_and_name", "exact_code"})
REFERENCE_MATCH_METHOD = "exact_code"


@dataclass(frozen=True)
class HistoricalFundingIdentityInput:
    source_institution_key: str
    source_institution_name: str
    source_crno: str | None = None


@dataclass(frozen=True)
class HistoricalFundingIdentityResolution:
    source_institution_key: str
    institution_id: str | None
    method: str | None
    reason: str


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _normalized_cutoff(value: date | datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.max)
    else:
        text_value = _required_text(value, field="knowledge_as_of")
        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed_date = date.fromisoformat(text_value)
            except ValueError as exc:
                raise ValueError("knowledge_as_of must be ISO date/datetime") from exc
            parsed = datetime.combine(parsed_date, time.max)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _parse_datetime(value: object) -> datetime | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _parse_date(value: object) -> date | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    return date.fromisoformat(text_value[:10])


def _payload_crno(value: object) -> str | None:
    if value is None:
        return None
    payload: object = value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, Mapping):
        return None
    crno = str(payload.get("crno") or "").strip()
    return crno or None


def _recorded_by_cutoff(row: sqlite3.Row, cutoff: datetime) -> bool:
    created_at = _parse_datetime(row["created_at"])
    return created_at is not None and created_at <= cutoff


def _not_closed_by_cutoff(row: sqlite3.Row, cutoff: datetime) -> bool:
    valid_to = _parse_date(row["valid_to"])
    return valid_to is None or valid_to > cutoff.date()


def _direct_link_eligible(row: sqlite3.Row, cutoff: datetime) -> bool:
    if str(row["match_method"]) not in DIRECT_MATCH_METHODS:
        return False
    if not _recorded_by_cutoff(row, cutoff) or not _not_closed_by_cutoff(row, cutoff):
        return False
    valid_from = _parse_date(row["valid_from"])
    return valid_from is None or valid_from <= cutoff.date()


def _reference_link_eligible(row: sqlite3.Row, cutoff: datetime) -> bool:
    if str(row["match_method"]) != REFERENCE_MATCH_METHOD:
        return False
    if not _recorded_by_cutoff(row, cutoff) or not _not_closed_by_cutoff(row, cutoff):
        return False
    valid_from = _parse_date(row["valid_from"])
    # FSB/Finlife exact-code links have temporal source validity. Missing
    # ``valid_from`` cannot be promoted to historical proof.
    return valid_from is not None and valid_from <= cutoff.date()


def _crno_conflicts(source_crno: str | None, links: Iterable[sqlite3.Row]) -> bool:
    normalized = str(source_crno or "").strip() or None
    if normalized is None:
        return False
    reference_crnos = {
        value
        for value in (_payload_crno(link["source_payload_json"]) for link in links)
        if value is not None
    }
    return any(value != normalized for value in reference_crnos)


def _open_immutable_snapshot(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def resolve_historical_savings_bank_funding_identities(
    db_path: Path,
    *,
    inputs: Iterable[HistoricalFundingIdentityInput],
    knowledge_as_of: date | datetime | str,
) -> dict[str, HistoricalFundingIdentityResolution]:
    """Resolve source funding keys without trusting mutable observation identity."""

    cutoff = _normalized_cutoff(knowledge_as_of)
    normalized_inputs: dict[str, HistoricalFundingIdentityInput] = {}
    for item in inputs:
        source_key = _required_text(
            item.source_institution_key,
            field="source_institution_key",
        )
        source_name = _required_text(
            item.source_institution_name,
            field="source_institution_name",
        )
        prior = normalized_inputs.get(source_key)
        if prior is not None and (
            prior.source_institution_name != source_name
            or (prior.source_crno or "") != (item.source_crno or "")
        ):
            raise ValueError(
                "historical funding source key has conflicting identity metadata: "
                f"{source_key}"
            )
        normalized_inputs[source_key] = HistoricalFundingIdentityInput(
            source_institution_key=source_key,
            source_institution_name=source_name,
            source_crno=str(item.source_crno or "").strip() or None,
        )
    if not normalized_inputs:
        return {}

    org_keys = {
        source_key: make_org_key(
            sector=SAVINGS_BANK_SECTOR,
            source_institution_key=source_key,
            institution_name=item.source_institution_name,
        )
        for source_key, item in normalized_inputs.items()
    }
    placeholders = ",".join("?" for _ in org_keys)
    connection = _open_immutable_snapshot(db_path)
    try:
        links = connection.execute(
            f"""
            SELECT source_id, source_entity_key, entity_id, match_method,
                   source_payload_json, valid_from, valid_to, created_at
            FROM source_entity_links
            WHERE entity_type = 'institution'
              AND source_id IN (?, ?, ?)
              AND source_entity_key IN ({placeholders})
            ORDER BY source_id, source_entity_key, created_at
            """,
            (
                DATA_GO_SAVINGS_BANK_SOURCE_ID,
                FSB_SOURCE_ID,
                FINLIFE_SAVINGS_BANK_SOURCE_ID,
                *sorted(org_keys.values()),
            ),
        ).fetchall()
    finally:
        connection.close()

    by_source_key: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for link in links:
        by_source_key.setdefault(
            (str(link["source_id"]), str(link["source_entity_key"])), []
        ).append(link)

    resolutions: dict[str, HistoricalFundingIdentityResolution] = {}
    for source_key, item in sorted(normalized_inputs.items()):
        org_key = org_keys[source_key]
        direct = [
            link
            for link in by_source_key.get((DATA_GO_SAVINGS_BANK_SOURCE_ID, org_key), [])
            if _direct_link_eligible(link, cutoff)
        ]
        if len(direct) > 1:
            raise ValueError(
                "multiple direct funding identity links valid at historical cutoff: "
                f"source_key={source_key}"
            )
        if len(direct) == 1:
            if _crno_conflicts(item.source_crno, direct):
                resolutions[source_key] = HistoricalFundingIdentityResolution(
                    source_institution_key=source_key,
                    institution_id=None,
                    method=None,
                    reason="direct_link_crno_conflict",
                )
                continue
            resolutions[source_key] = HistoricalFundingIdentityResolution(
                source_institution_key=source_key,
                institution_id=str(direct[0]["entity_id"]),
                method="direct_exact_code_name_recorded_by_cutoff",
                reason="resolved",
            )
            continue

        fsb = [
            link
            for link in by_source_key.get((FSB_SOURCE_ID, org_key), [])
            if _reference_link_eligible(link, cutoff)
        ]
        finlife = [
            link
            for link in by_source_key.get((FINLIFE_SAVINGS_BANK_SOURCE_ID, org_key), [])
            if _reference_link_eligible(link, cutoff)
        ]
        if len(fsb) != 1 or len(finlife) != 1:
            resolutions[source_key] = HistoricalFundingIdentityResolution(
                source_institution_key=source_key,
                institution_id=None,
                method=None,
                reason="reference_link_cardinality_at_cutoff",
            )
            continue
        if str(fsb[0]["entity_id"]) != str(finlife[0]["entity_id"]):
            resolutions[source_key] = HistoricalFundingIdentityResolution(
                source_institution_key=source_key,
                institution_id=None,
                method=None,
                reason="reference_entity_conflict_at_cutoff",
            )
            continue
        if _crno_conflicts(item.source_crno, (fsb[0], finlife[0])):
            resolutions[source_key] = HistoricalFundingIdentityResolution(
                source_institution_key=source_key,
                institution_id=None,
                method=None,
                reason="reference_crno_conflict_at_cutoff",
            )
            continue
        resolutions[source_key] = HistoricalFundingIdentityResolution(
            source_institution_key=source_key,
            institution_id=str(fsb[0]["entity_id"]),
            method="fsb_finlife_exact_code_consensus_recorded_by_cutoff",
            reason="resolved",
        )

    return resolutions
