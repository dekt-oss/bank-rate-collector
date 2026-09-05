"""Exact cross-source identity reconciliation for NH local observations.

Data.go agricultural-cooperative institution keys embed the six-digit NH BRC
used by the official NH rate directory. The BRC relation is deterministic, but
historical names show mergers/renames. Therefore this module maps each active
observation independently only when BRC *and* normalized source name match the
active official ``nh_local`` institution link.

Callers may scope reconciliation to one metric and/or source month. This is
important for total-assets persistence: writing ``total_assets`` must never
modify an existing ``deposit_liabilities_total`` observation as a side effect.
The default remains unscoped for the pre-existing funding maintenance command.

It deliberately does not create a permanent funding SourceEntityLink: doing so
would cause one exact observation to absorb historical rows whose names differ.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from rate_monitor.collectors.data_go_funding.aggregate_policy import (
    is_agri_coop_institution_key,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.normalization import normalize_institution_name

FUNDING_SOURCE_ID = "data_go_agri_coop_funding"
NH_RATE_SOURCE_ID = "nh_local"
MAPPED_STATUS = "mapped_exact_nh_brc_name"


class FundingIdentityConflict(RuntimeError):
    """An observation is already mapped to a different canonical institution."""


@dataclass(frozen=True)
class FundingIdentityReconciliationResult:
    scanned: int
    eligible: int
    mapped: int
    unchanged: int
    no_brc_link: int
    name_mismatch: int
    invalid_link: int


def _nh_org_key(brc: str) -> str:
    return f"nh_local:{brc}"


def reconcile_agri_funding_identity(
    db_path: Path,
    *,
    metric_code: str | None = None,
    source_effective_month: str | None = None,
) -> FundingIdentityReconciliationResult:
    """Map active NH observations using exact BRC + official source name.

    Amount, revision, validity and raw provenance are never changed. A row that
    already points at a different institution fails the whole transaction.
    Optional selectors constrain which observations may be mutated; they do not
    weaken the exact BRC + normalized-name identity contract.
    """
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)

    scanned = eligible = mapped = unchanged = 0
    no_brc_link = name_mismatch = invalid_link = 0

    with session_scope(factory) as session:
        statement = select(InstitutionFundingObservation).where(
            InstitutionFundingObservation.source_id == FUNDING_SOURCE_ID,
            InstitutionFundingObservation.valid_to.is_(None),
        )
        if metric_code is not None:
            statement = statement.where(
                InstitutionFundingObservation.metric_code == metric_code
            )
        if source_effective_month is not None:
            statement = statement.where(
                InstitutionFundingObservation.source_effective_month
                == source_effective_month
            )
        observations = list(
            session.scalars(
                statement.order_by(
                    InstitutionFundingObservation.source_effective_month,
                    InstitutionFundingObservation.source_institution_key,
                )
            )
        )
        scanned = len(observations)

        links = list(
            session.scalars(
                select(m.SourceEntityLink).where(
                    m.SourceEntityLink.source_id == NH_RATE_SOURCE_ID,
                    m.SourceEntityLink.entity_type == "institution",
                    m.SourceEntityLink.valid_to.is_(None),
                )
            )
        )
        link_by_key = {link.source_entity_key: link for link in links}

        for observation in observations:
            source_key = observation.source_institution_key
            if not is_agri_coop_institution_key(source_key):
                continue
            eligible += 1
            brc = source_key[-6:]
            link = link_by_key.get(_nh_org_key(brc))
            if link is None:
                no_brc_link += 1
                continue

            source_name = str(link.source_name or "").strip()
            if not source_name or normalize_institution_name(
                source_name
            ) != normalize_institution_name(observation.source_institution_name):
                name_mismatch += 1
                continue

            institution = session.get(m.Institution, link.entity_id)
            if institution is None or institution.sector != "nh_local":
                invalid_link += 1
                continue

            if (
                observation.institution_id is not None
                and observation.institution_id != institution.id
            ):
                raise FundingIdentityConflict(
                    "NH funding observation identity conflict: "
                    f"source_key={source_key} month={observation.source_effective_month} "
                    f"existing={observation.institution_id} candidate={institution.id}"
                )

            if (
                observation.institution_id == institution.id
                and observation.identity_status == MAPPED_STATUS
            ):
                unchanged += 1
                continue

            observation.institution_id = institution.id
            observation.identity_status = MAPPED_STATUS
            mapped += 1

    return FundingIdentityReconciliationResult(
        scanned=scanned,
        eligible=eligible,
        mapped=mapped,
        unchanged=unchanged,
        no_brc_link=no_brc_link,
        name_mismatch=name_mismatch,
        invalid_link=invalid_link,
    )
