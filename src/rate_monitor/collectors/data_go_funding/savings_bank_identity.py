"""Fail-closed savings-bank funding identity consensus.

Data.go ``fncoCd`` rows can use legal/Korean spellings while the current FSB and
Finlife surfaces use acronym/brand spellings.  We do not relax the repository's
global code+name identity guard.  Instead, a name-mismatched Data.go observation
may be mapped only when the two existing official savings-bank sources each have
one active ``exact_code`` link for the same org key and both links point to the
same active savings-bank canonical institution.

This helper is intentionally observation-level evidence.  Callers must not turn
a dual-source result into a persistent Data.go ``SourceEntityLink`` because that
would let a later FSB/Finlife divergence bypass this consensus gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from rate_monitor.db import models as m
from rate_monitor.domain.identifiers import make_org_key

FSB_SOURCE_ID = "fsb"
FINLIFE_SAVINGS_BANK_SOURCE_ID = "finlife_savings_bank"
REFERENCE_SOURCE_IDS = (FSB_SOURCE_ID, FINLIFE_SAVINGS_BANK_SOURCE_ID)
SAVINGS_BANK_SECTOR = "savings_bank"
SAVINGS_BANK_SECTOR_TOTAL_KEY = "030350S"
MAPPED_DUAL_SOURCE_STATUS = "mapped_dual_source"


@dataclass(frozen=True)
class SavingsBankIdentityConsensus:
    institution_id: str | None
    reason: str


def _payload_crno(link: m.SourceEntityLink) -> str | None:
    payload = link.source_payload_json or {}
    crno = str(payload.get("crno") or "").strip()
    return crno or None


def resolve_savings_bank_dual_source_consensus(
    session: Any,
    *,
    source_institution_key: str,
    source_institution_name: str,
    source_crno: str | None,
) -> SavingsBankIdentityConsensus:
    """Resolve one Data.go savings-bank row from strict FSB+Finlife consensus.

    No fuzzy/name-only/CRNO-only path exists here.  Missing, duplicate, stale,
    non-exact, cross-sector, inactive or disagreeing reference evidence fails
    closed.  A CRNO present on either reference link also acts as a conflict
    guard, but absence of reference CRNO is not treated as positive evidence.
    """
    if source_institution_key == SAVINGS_BANK_SECTOR_TOTAL_KEY:
        return SavingsBankIdentityConsensus(None, "sector_total_excluded")

    org_key = make_org_key(
        sector=SAVINGS_BANK_SECTOR,
        source_institution_key=source_institution_key,
        institution_name=source_institution_name,
    )
    links = list(
        session.scalars(
            select(m.SourceEntityLink).where(
                m.SourceEntityLink.source_id.in_(REFERENCE_SOURCE_IDS),
                m.SourceEntityLink.entity_type == "institution",
                m.SourceEntityLink.source_entity_key == org_key,
                m.SourceEntityLink.valid_to.is_(None),
            )
        )
    )

    by_source = {
        source_id: [link for link in links if link.source_id == source_id]
        for source_id in REFERENCE_SOURCE_IDS
    }
    if any(len(by_source[source_id]) != 1 for source_id in REFERENCE_SOURCE_IDS):
        return SavingsBankIdentityConsensus(None, "reference_link_cardinality")

    fsb_link = by_source[FSB_SOURCE_ID][0]
    finlife_link = by_source[FINLIFE_SAVINGS_BANK_SOURCE_ID][0]
    if fsb_link.match_method != "exact_code" or finlife_link.match_method != "exact_code":
        return SavingsBankIdentityConsensus(None, "reference_link_not_exact_code")
    if fsb_link.entity_id != finlife_link.entity_id:
        return SavingsBankIdentityConsensus(None, "reference_entity_conflict")

    institution = session.get(m.Institution, fsb_link.entity_id)
    if institution is None or institution.sector != SAVINGS_BANK_SECTOR or not institution.active:
        return SavingsBankIdentityConsensus(None, "invalid_canonical_institution")

    normalized_source_crno = str(source_crno or "").strip() or None
    if normalized_source_crno:
        reference_crnos = {
            crno
            for crno in (_payload_crno(fsb_link), _payload_crno(finlife_link))
            if crno is not None
        }
        if any(crno != normalized_source_crno for crno in reference_crnos):
            return SavingsBankIdentityConsensus(None, "reference_crno_conflict")

    return SavingsBankIdentityConsensus(
        institution.id,
        "fsb_finlife_exact_code_consensus",
    )
