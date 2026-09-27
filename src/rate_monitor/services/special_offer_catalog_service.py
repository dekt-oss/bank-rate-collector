"""Independent bank-direct special-offer evidence catalog.

This registry is intentionally outside the canonical rate Product identity. It stores
explicit official product evidence even when the product is absent from the current
FSB universe. Only the Strategy special-offer Radar may consume these rows.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from rate_monitor.db.special_offer_models import OfficialSpecialOfferCatalogEvidence
from rate_monitor.domain.normalization import normalize_institution_name

CONFIRMED_SPECIAL = "confirmed_special"
CONFIRMED_NORMAL = "confirmed_normal"
CLASSIFICATIONS = frozenset({CONFIRMED_SPECIAL, CONFIRMED_NORMAL})
AVAILABILITY_STATUSES = frozenset(
    {"confirmed_active", "confirmed_ended", "unknown"}
)


class OfficialSpecialOfferCatalogError(ValueError):
    """Catalog evidence failed a fail-closed contract."""


@dataclass(frozen=True)
class OfficialSpecialOfferCatalogInput:
    institution_name: str
    official_product_key: str
    product_name: str
    classification: str
    availability_status: str
    snapshot_as_of: date
    observed_at: datetime
    source_locator: str
    content_hash: str
    source_effective_from: date | None = None
    source_effective_to: date | None = None
    evidence: dict[str, Any] | None = None
    canonical_product_id: str | None = None
    binding_status: str = "unbound"


def _required(value: object, field: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise OfficialSpecialOfferCatalogError(f"{field} is required")
    return cleaned


def _source_namespace(locator: str) -> str:
    parsed = urlparse(locator)
    if parsed.scheme != "https" or not parsed.hostname:
        raise OfficialSpecialOfferCatalogError(
            "official catalog source_locator must be an HTTPS URL"
        )
    return f"bank_direct:{parsed.hostname.lower()}"


def _validate(item: OfficialSpecialOfferCatalogInput) -> dict[str, Any]:
    classification = _required(item.classification, "classification")
    if classification not in CLASSIFICATIONS:
        raise OfficialSpecialOfferCatalogError(
            f"unsupported classification: {classification}"
        )
    availability = _required(item.availability_status, "availability_status")
    if availability not in AVAILABILITY_STATUSES:
        raise OfficialSpecialOfferCatalogError(
            f"unsupported availability_status: {availability}"
        )
    if item.source_effective_to is not None and item.source_effective_from is None:
        raise OfficialSpecialOfferCatalogError(
            "source_effective_to requires source_effective_from"
        )
    if (
        item.source_effective_from is not None
        and item.source_effective_to is not None
        and item.source_effective_to < item.source_effective_from
    ):
        raise OfficialSpecialOfferCatalogError("source effective period is reversed")
    content_hash = _required(item.content_hash, "content_hash")
    if not content_hash.startswith("sha256:") or len(content_hash) != 71:
        raise OfficialSpecialOfferCatalogError(
            "content_hash must be sha256-prefixed with 64 hex characters"
        )
    try:
        int(content_hash.removeprefix("sha256:"), 16)
    except ValueError as exc:
        raise OfficialSpecialOfferCatalogError("content_hash must be hexadecimal") from exc

    evidence = dict(item.evidence or {})
    if evidence.get("identity_marker_present") is not True:
        raise OfficialSpecialOfferCatalogError(
            "catalog evidence requires an explicit official product identity marker"
        )
    if evidence.get("explicit_phrases_present") is not True:
        raise OfficialSpecialOfferCatalogError(
            "catalog evidence requires explicit special-offer source phrases"
        )
    if availability == "confirmed_active":
        availability_evidence = dict(evidence.get("availability") or {})
        if availability_evidence.get("status") != "confirmed_active":
            raise OfficialSpecialOfferCatalogError(
                "confirmed_active requires explicit availability evidence"
            )
        if not str(availability_evidence.get("assertion_text") or "").strip():
            raise OfficialSpecialOfferCatalogError(
                "confirmed_active requires an availability assertion"
            )
    return evidence


def _evidence_key(
    *,
    source_namespace: str,
    institution_normalized: str,
    item: OfficialSpecialOfferCatalogInput,
    evidence: dict[str, Any],
) -> str:
    payload = {
        "source_namespace": source_namespace,
        "institution_normalized": institution_normalized,
        "official_product_key": item.official_product_key,
        "product_name": item.product_name,
        "classification": item.classification,
        "availability_status": item.availability_status,
        "snapshot_as_of": item.snapshot_as_of.isoformat(),
        "source_effective_from": (
            item.source_effective_from.isoformat()
            if item.source_effective_from
            else None
        ),
        "source_effective_to": (
            item.source_effective_to.isoformat() if item.source_effective_to else None
        ),
        "content_hash": item.content_hash,
        "evidence": evidence,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def append_official_catalog_evidence(
    session: Session,
    item: OfficialSpecialOfferCatalogInput,
) -> OfficialSpecialOfferCatalogEvidence:
    institution_name = _required(item.institution_name, "institution_name")
    official_product_key = _required(item.official_product_key, "official_product_key")
    product_name = _required(item.product_name, "product_name")
    locator = _required(item.source_locator, "source_locator")
    namespace = _source_namespace(locator)
    evidence = _validate(item)
    institution_normalized = normalize_institution_name(institution_name)
    key = _evidence_key(
        source_namespace=namespace,
        institution_normalized=institution_normalized,
        item=item,
        evidence=evidence,
    )
    existing = session.scalar(
        select(OfficialSpecialOfferCatalogEvidence).where(
            OfficialSpecialOfferCatalogEvidence.evidence_key == key
        )
    )
    if existing is not None:
        return existing

    record = OfficialSpecialOfferCatalogEvidence(
        source_namespace=namespace,
        institution_name=institution_name,
        institution_normalized=institution_normalized,
        official_product_key=official_product_key,
        product_name=product_name,
        classification=item.classification,
        availability_status=item.availability_status,
        snapshot_as_of=item.snapshot_as_of,
        source_effective_from=item.source_effective_from,
        source_effective_to=item.source_effective_to,
        observed_at=item.observed_at,
        source_locator=locator,
        content_hash=item.content_hash,
        evidence_key=key,
        evidence_json=evidence,
        canonical_product_id=item.canonical_product_id,
        binding_status=item.binding_status,
        created_at=item.observed_at,
    )
    session.add(record)
    session.flush()
    return record


def import_capture_payload(
    session: Session,
    payload: dict[str, Any],
) -> list[OfficialSpecialOfferCatalogEvidence]:
    """Append explicit confirmed-special candidates from an R3-C capture payload."""
    observed_raw = _required(payload.get("observed_at"), "observed_at")
    observed = datetime.fromisoformat(observed_raw)
    if observed.tzinfo is not None:
        observed = observed.astimezone(UTC).replace(tzinfo=None)
    records: list[OfficialSpecialOfferCatalogEvidence] = []
    for captured in payload.get("captures") or []:
        if captured.get("classification_candidate") != "confirmed_special_candidate":
            continue
        terms = dict(captured.get("special_offer_terms") or {})
        availability = dict(captured.get("availability") or {})
        effective_from = (
            date.fromisoformat(str(terms["sale_start"]))
            if terms.get("sale_start")
            else None
        )
        effective_to = (
            date.fromisoformat(str(terms["sale_end"]))
            if terms.get("sale_end")
            else None
        )
        records.append(
            append_official_catalog_evidence(
                session,
                OfficialSpecialOfferCatalogInput(
                    institution_name=str(captured.get("institution") or ""),
                    official_product_key=str(captured.get("official_product_key") or ""),
                    product_name=str(captured.get("product_name") or ""),
                    classification=CONFIRMED_SPECIAL,
                    availability_status=str(availability.get("status") or "unknown"),
                    snapshot_as_of=observed.date(),
                    observed_at=observed,
                    source_locator=str(captured.get("source_locator") or ""),
                    content_hash=str(captured.get("content_sha256") or ""),
                    source_effective_from=effective_from,
                    source_effective_to=effective_to,
                    evidence={
                        "identity_scope": "official_product_key",
                        "identity_marker_present": captured.get(
                            "identity_marker_present"
                        )
                        is True,
                        "explicit_phrases_present": captured.get(
                            "explicit_phrases_present"
                        )
                        is True,
                        "special_offer_terms": terms,
                        "availability": availability,
                        "capture_target_id": captured.get("target_id"),
                        "classification_basis": "explicit_bank_direct_product_evidence",
                    },
                    binding_status="unbound",
                ),
            )
        )
    return records
