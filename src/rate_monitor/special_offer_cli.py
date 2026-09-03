"""특판 evidence registry 운영 검수 CLI.

자동 판정 도구가 아니다. ``list``/``summary``로 근거를 보고, 공식 상품 단위
근거를 사람이 확인한 경우에만 ``confirm``으로 append-only 확정 근거를 남긴다.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime

from rate_monitor.db.session import (
    DEFAULT_DB_PATH,
    create_db_engine,
    make_session_factory,
    session_scope,
)
from rate_monitor.services.special_offer_evidence_service import (
    CONFIRMED_NORMAL,
    CONFIRMED_SPECIAL,
    EXPLICIT_SOURCE_FIELD,
    VERSIONED_PRODUCT_SCOPE,
    SpecialOfferEvidenceError,
)
from rate_monitor.services.special_offer_review_service import (
    append_operator_confirmation,
    list_special_offer_evidence,
    summarize_special_offer_evidence,
)


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _factory(db: str):
    return make_session_factory(create_db_engine(db))


def _summary(args: argparse.Namespace) -> int:
    with session_scope(_factory(args.db)) as session:
        payload = summarize_special_offer_evidence(session)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def _list(args: argparse.Namespace) -> int:
    with session_scope(_factory(args.db)) as session:
        rows = list_special_offer_evidence(
            session,
            classification=args.classification,
            source_id=args.source,
            limit=args.limit,
        )
    print(
        json.dumps(
            [asdict(row) for row in rows],
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
    )
    return 0


def _confirm(args: argparse.Namespace) -> int:
    observed_at = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(_factory(args.db)) as session:
        record = append_operator_confirmation(
            session,
            source_id=args.source,
            product_id=args.product_id,
            classification=args.classification,
            evidence_kind=args.evidence_kind,
            snapshot_as_of=date.fromisoformat(args.snapshot_as_of),
            observed_at=observed_at,
            source_locator=args.source_locator,
            evidence_ref=args.evidence_ref,
            content_sha256=args.content_sha256,
            source_effective_from=(
                date.fromisoformat(args.effective_from) if args.effective_from else None
            ),
            source_effective_to=(
                date.fromisoformat(args.effective_to) if args.effective_to else None
            ),
            note=args.note,
        )
        payload = {
            "evidence_id": record.id,
            "source_id": record.source_id,
            "product_id": record.product_id,
            "source_product_key": record.source_product_key,
            "classification": record.classification,
            "evidence_kind": record.evidence_kind,
            "snapshot_as_of": record.snapshot_as_of,
            "source_effective_from": record.source_effective_from,
            "source_effective_to": record.source_effective_to,
            "observed_at": record.observed_at,
            "evidence_ref": record.evidence_ref,
            "content_hash": record.content_hash,
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rate-monitor-special-offer")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    summary = sub.add_parser("summary", help="분류별 evidence 행/상품 수를 본다")
    summary.set_defaults(func=_summary)

    listing = sub.add_parser("list", help="최근 evidence를 상품 문맥과 함께 본다")
    listing.add_argument("--source", default="fsb")
    listing.add_argument(
        "--classification",
        choices=["unknown", CONFIRMED_SPECIAL, CONFIRMED_NORMAL],
        default=None,
    )
    listing.add_argument("--limit", type=int, default=50)
    listing.set_defaults(func=_list)

    confirm = sub.add_parser(
        "confirm",
        help="사람이 확인한 상품 단위 공식 근거를 append-only 확정 evidence로 남긴다",
    )
    confirm.add_argument("--source", default="fsb")
    confirm.add_argument("--product-id", required=True)
    confirm.add_argument(
        "--classification",
        required=True,
        choices=[CONFIRMED_SPECIAL, CONFIRMED_NORMAL],
    )
    confirm.add_argument(
        "--evidence-kind",
        required=True,
        choices=[EXPLICIT_SOURCE_FIELD, VERSIONED_PRODUCT_SCOPE],
    )
    confirm.add_argument(
        "--snapshot-as-of",
        required=True,
        help="판정 대상 snapshot 날짜 YYYY-MM-DD. 실행 시각으로 자동 대체하지 않는다",
    )
    confirm.add_argument("--source-locator", required=True)
    confirm.add_argument("--evidence-ref", required=True)
    confirm.add_argument(
        "--content-sha256",
        required=True,
        help="검수한 공식 근거 내용의 SHA-256 64자리 hex",
    )
    confirm.add_argument(
        "--effective-from",
        default=None,
        help="공식 근거가 명시한 적용 시작일 YYYY-MM-DD",
    )
    confirm.add_argument(
        "--effective-to",
        default=None,
        help="공식 근거가 명시한 적용 종료일 YYYY-MM-DD",
    )
    confirm.add_argument("--note", default=None)
    confirm.set_defaults(func=_confirm)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SpecialOfferEvidenceError, ValueError) as exc:
        print(f"특판 evidence 검수 오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
