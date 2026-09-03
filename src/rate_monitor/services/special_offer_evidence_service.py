"""특판 근거의 검증·append-only 저장·point-in-time 해석.

자유문구나 상품명 휴리스틱은 판정을 만들 수 없다. 공식 snapshot 원문은
우선 ``unknown``으로 쌓고, 상품 단위의 명시적 근거가 검수된 경우에만
``confirmed_special`` 또는 ``confirmed_normal``을 기록한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rate_monitor.db.models import CollectionRun, Product, RawArtifact, SourceEntityLink
from rate_monitor.db.special_offer_models import ProductSpecialOfferEvidence
from rate_monitor.domain.schemas import ParsedRateRow

UNKNOWN = "unknown"
CONFIRMED_SPECIAL = "confirmed_special"
CONFIRMED_NORMAL = "confirmed_normal"
CLASSIFICATIONS = frozenset({UNKNOWN, CONFIRMED_SPECIAL, CONFIRMED_NORMAL})

SOURCE_SNAPSHOT = "source_snapshot"
EXPLICIT_SOURCE_FIELD = "explicit_source_field"
VERSIONED_PRODUCT_SCOPE = "versioned_product_scope_observation"
CONFIRMING_KINDS = frozenset({EXPLICIT_SOURCE_FIELD, VERSIONED_PRODUCT_SCOPE})


class SpecialOfferEvidenceError(ValueError):
    """근거가 특판 판정 계약을 충족하지 못했다."""


@dataclass(frozen=True)
class SpecialOfferEvidenceInput:
    source_id: str
    product_id: str
    source_product_key: str
    classification: str
    evidence_kind: str
    snapshot_as_of: date
    observed_at: datetime
    source_locator: str
    evidence_ref: str
    content_hash: str
    raw_artifact_id: str | None = None
    source_effective_from: date | None = None
    source_effective_to: date | None = None
    evidence: dict[str, Any] | None = None


@dataclass(frozen=True)
class ResolvedSpecialOfferState:
    classification: str
    special_offer_flag: bool | None
    evidence_kind: str | None
    evidence_ref: str | None
    evidence_ids: tuple[str, ...]
    conflict: bool = False


def _required(value: object, field: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise SpecialOfferEvidenceError(f"{field} is required")
    return cleaned


def _identity_link(session: Session, item: SpecialOfferEvidenceInput) -> SourceEntityLink:
    product = session.get(Product, item.product_id)
    if product is None:
        raise SpecialOfferEvidenceError("product_id does not exist")
    expected_key = f"{product.institution_id}:{item.source_product_key}"
    links = session.scalars(
        select(SourceEntityLink).where(
            SourceEntityLink.source_id == item.source_id,
            SourceEntityLink.entity_type == "product",
            SourceEntityLink.source_entity_key == expected_key,
            SourceEntityLink.entity_id == item.product_id,
            SourceEntityLink.valid_to.is_(None),
        )
    ).all()
    if len(links) != 1 or links[0].match_method != "exact_code":
        raise SpecialOfferEvidenceError(
            "special-offer evidence requires one active exact_code product link"
        )
    return links[0]


def _validate(item: SpecialOfferEvidenceInput) -> dict[str, Any]:
    classification = _required(item.classification, "classification")
    kind = _required(item.evidence_kind, "evidence_kind")
    if classification not in CLASSIFICATIONS:
        raise SpecialOfferEvidenceError(f"unsupported classification: {classification}")
    if item.source_effective_to is not None and item.source_effective_from is None:
        raise SpecialOfferEvidenceError("source_effective_to requires source_effective_from")
    if (
        item.source_effective_from is not None
        and item.source_effective_to is not None
        and item.source_effective_to < item.source_effective_from
    ):
        raise SpecialOfferEvidenceError("source effective period is reversed")

    evidence = dict(item.evidence or {})
    if classification == UNKNOWN:
        if kind != SOURCE_SNAPSHOT:
            raise SpecialOfferEvidenceError("unknown evidence must be a source_snapshot")
    else:
        if kind not in CONFIRMING_KINDS:
            raise SpecialOfferEvidenceError(
                "confirmed classification requires an approved explicit evidence kind"
            )
        if evidence.get("identity_scope") != "exact_product":
            raise SpecialOfferEvidenceError(
                "confirmed classification requires product-specific identity evidence"
            )
        if _required(evidence.get("explicit_assertion"), "explicit_assertion") != classification:
            raise SpecialOfferEvidenceError(
                "explicit_assertion must equal the confirmed classification"
            )
        # 현재 페이지를 과거에 소급하지 않는다. 과거 snapshot 판정은 페이지가
        # 스스로 밝힌 적용기간이 있을 때만 허용한다.
        if item.snapshot_as_of < item.observed_at.date() and item.source_effective_from is None:
            raise SpecialOfferEvidenceError(
                "current evidence cannot be carried back without an explicit effective period"
            )
    return evidence


def _evidence_key(item: SpecialOfferEvidenceInput, evidence: dict[str, Any]) -> str:
    payload = {
        "source_id": item.source_id,
        "product_id": item.product_id,
        "source_product_key": item.source_product_key,
        "classification": item.classification,
        "evidence_kind": item.evidence_kind,
        "snapshot_as_of": item.snapshot_as_of.isoformat(),
        "source_effective_from": (
            item.source_effective_from.isoformat() if item.source_effective_from else None
        ),
        "source_effective_to": (
            item.source_effective_to.isoformat() if item.source_effective_to else None
        ),
        "source_locator": item.source_locator,
        "evidence_ref": item.evidence_ref,
        "content_hash": item.content_hash,
        "evidence": evidence,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def append_special_offer_evidence(
    session: Session, item: SpecialOfferEvidenceInput
) -> ProductSpecialOfferEvidence:
    """검증된 불변 근거를 저장한다. 동일 근거 재처리는 같은 행을 돌려준다."""
    _required(item.source_id, "source_id")
    _required(item.product_id, "product_id")
    _required(item.source_product_key, "source_product_key")
    _required(item.source_locator, "source_locator")
    _required(item.evidence_ref, "evidence_ref")
    content_hash = _required(item.content_hash, "content_hash")
    if not content_hash.startswith("sha256:") or len(content_hash) <= len("sha256:"):
        raise SpecialOfferEvidenceError("content_hash must be sha256-prefixed")
    _identity_link(session, item)
    if item.raw_artifact_id is not None:
        artifact_source = session.scalar(
            select(CollectionRun.source_id)
            .join(RawArtifact, RawArtifact.run_id == CollectionRun.id)
            .where(RawArtifact.id == item.raw_artifact_id)
        )
        if artifact_source != item.source_id:
            raise SpecialOfferEvidenceError(
                "raw_artifact_id must belong to the evidence source"
            )
    evidence = _validate(item)
    key = _evidence_key(item, evidence)
    existing = session.scalar(
        select(ProductSpecialOfferEvidence).where(ProductSpecialOfferEvidence.evidence_key == key)
    )
    if existing is not None:
        return existing

    record = ProductSpecialOfferEvidence(
        source_id=item.source_id,
        product_id=item.product_id,
        source_product_key=item.source_product_key,
        classification=item.classification,
        evidence_kind=item.evidence_kind,
        snapshot_as_of=item.snapshot_as_of,
        source_effective_from=item.source_effective_from,
        source_effective_to=item.source_effective_to,
        observed_at=item.observed_at,
        source_locator=item.source_locator,
        evidence_ref=item.evidence_ref,
        raw_artifact_id=item.raw_artifact_id,
        content_hash=item.content_hash,
        evidence_key=key,
        evidence_json=evidence,
        created_at=item.observed_at,
    )
    session.add(record)
    session.flush()
    return record


def append_unknown_fsb_snapshot(
    session: Session,
    *,
    row: ParsedRateRow,
    product: Product,
    artifact: RawArtifact,
    observed_at: datetime,
) -> ProductSpecialOfferEvidence | None:
    """FSB 상품행을 판정 없이 보존한다. FSB 이외 원천에는 영향이 없다."""
    if row.source_id != "fsb" or not row.source_product_key:
        return None
    raw_as_of = str(row.extra.get("snapshot_as_of") or "").strip()
    snapshot_as_of = date.fromisoformat(raw_as_of) if raw_as_of else observed_at.date()
    product_url = str(row.extra.get("product_url") or "").strip()
    locator = row.base_source_locator.rsplit(".", 1)[0]
    return append_special_offer_evidence(
        session,
        SpecialOfferEvidenceInput(
            source_id=row.source_id,
            product_id=product.id,
            source_product_key=row.source_product_key,
            classification=UNKNOWN,
            evidence_kind=SOURCE_SNAPSHOT,
            snapshot_as_of=snapshot_as_of,
            observed_at=observed_at,
            source_locator=locator,
            evidence_ref=product_url or locator,
            raw_artifact_id=artifact.id,
            content_hash="sha256:" + row.source_record_hash.removeprefix("sha256:"),
            evidence={
                "identity_scope": "exact_product",
                "product_url": product_url or None,
                "source_product_name": row.product_name,
                "classification_basis": "not_provided_by_source_snapshot",
            },
        ),
    )


def resolve_special_offer_state(
    session: Session,
    *,
    product_id: str,
    as_of: date,
    known_at: datetime,
) -> ResolvedSpecialOfferState:
    """요청 snapshot에서 당시까지 알려진 판정만 푼다.

    exact snapshot이 있으면 기간형 근거보다 우선한다. 같은 최신 시각에 서로
    다른 판정이 있으면 한쪽을 고르지 않고 conflict/unknown으로 닫는다.
    """
    rows = session.scalars(
        select(ProductSpecialOfferEvidence).where(
            ProductSpecialOfferEvidence.product_id == product_id,
            ProductSpecialOfferEvidence.observed_at <= known_at,
        )
    ).all()
    exact = [row for row in rows if row.snapshot_as_of == as_of]
    exact_confirmed = [row for row in exact if row.classification != UNKNOWN]
    period_confirmed = [
        row
        for row in rows
        if row.classification != UNKNOWN
        if row.source_effective_from is not None
        and row.source_effective_from <= as_of
        and (row.source_effective_to is None or as_of <= row.source_effective_to)
    ]
    # unknown은 "원천이 말하지 않았다"는 뜻이지 normal/special의 반증이
    # 아니다. 따라서 명시적 적용기간 근거를 가리지 않는다.
    candidates = exact_confirmed or period_confirmed or exact
    if not candidates:
        return ResolvedSpecialOfferState(UNKNOWN, None, None, None, ())
    latest_at = max(row.observed_at for row in candidates)
    latest = [row for row in candidates if row.observed_at == latest_at]
    classifications = {row.classification for row in latest}
    ids = tuple(sorted(row.id for row in latest))
    if len(classifications) != 1:
        return ResolvedSpecialOfferState(UNKNOWN, None, None, None, ids, conflict=True)
    chosen = sorted(latest, key=lambda row: row.id)[0]
    flag = {
        UNKNOWN: None,
        CONFIRMED_SPECIAL: True,
        CONFIRMED_NORMAL: False,
    }[chosen.classification]
    return ResolvedSpecialOfferState(
        chosen.classification,
        flag,
        chosen.evidence_kind if flag is not None else None,
        chosen.evidence_ref if flag is not None else None,
        ids,
    )
