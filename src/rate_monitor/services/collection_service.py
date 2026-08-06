"""수집 오케스트레이션 (명세서 v3 §10.1).

    create_run → fetch → save_raw → parse → normalize → resolve
              → validate → persist → finalize

실패한 실행이 최신 정상값을 대체하지 않게 트랜잭션 경계를 지킨다 (v3 §10.3).
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from rate_monitor.collectors.base import SchemaChangedError, SourceBlockedError
from rate_monitor.db.models import (
    CollectionRun,
    RateObservation,
    RawArtifact,
    ReviewItem,
    Source,
)
from rate_monitor.db.session import session_scope
from rate_monitor.domain.enums import RunStatus, ValidationStatus
from rate_monitor.domain.schemas import CollectionRequest, ParsedRateRow, RawArtifactData
from rate_monitor.domain.timeutil import kst_path_stamp
from rate_monitor.services import entity_service

DEFAULT_RAW_ROOT = Path("data/raw")


@dataclass
class CollectionRunResult:
    run_id: str
    status: str
    raw_count: int
    parsed_count: int
    valid_count: int
    warning_count: int
    error_count: int
    message: str


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _content_hash(row: ParsedRateRow) -> str:
    """값 중복 검출용. 이전 실행과 같은 값인지 판정한다 (v3 §5.9)."""
    payload = "|".join(
        str(x)
        for x in (row.base_rate, row.max_rate, row.preference_raw, row.source_effective_at)
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_raw_artifacts(
    session: Session,
    run: CollectionRun,
    artifacts: list[RawArtifactData],
    raw_root: Path,
    now: datetime,
) -> list[RawArtifact]:
    """원본을 파일로 쓰고 DB에는 경로·해시만 남긴다 (v3 §5.3)."""
    day_dir = raw_root / kst_path_stamp(now) / run.id
    day_dir.mkdir(parents=True, exist_ok=True)

    saved: list[RawArtifact] = []
    for artifact in artifacts:
        path = day_dir / artifact.filename
        path.write_bytes(artifact.content)
        record = RawArtifact(
            run_id=run.id,
            artifact_type=artifact.artifact_type,
            relative_path=str(path),
            sha256=hashlib.sha256(artifact.content).hexdigest(),
            content_length=len(artifact.content),
            encoding="utf-8",
            request_meta_json=artifact.request_meta,
            captured_at=now,
        )
        session.add(record)
        saved.append(record)
    session.flush()
    return saved


def persist_rows(
    session: Session,
    run: CollectionRun,
    rows: list[ParsedRateRow],
    artifact: RawArtifact,
    now: datetime,
    seen_variants: set[str],
) -> tuple[int, int]:
    """표준 행을 저장한다. (정상 건수, 오류 건수)를 돌려준다.

    같은 실행 안에서 같은 비교 단위가 두 번 나오면 뒤엣것을 버리고 검수항목을
    남긴다. (variant_id, run_id) 유니크 제약을 미리 지킨다.

    `seen_variants`는 호출자가 실행 단위로 넘긴다. 아티팩트(페이지)마다
    새로 만들면 페이지 경계를 넘는 중복을 놓친다.
    """
    valid = 0
    errors = 0

    for row in rows:
        institution = entity_service.resolve_institution(session, row, now)
        outlet = entity_service.resolve_outlet(session, row, institution, now)
        # 금리가 기관 단위인 원천은 점포 명부를 따로 실어 보낸다.
        # 비어 있으면 아무 일도 하지 않는다.
        entity_service.resolve_outlet_directory(session, row, institution, now)
        product = entity_service.resolve_product(session, row, institution, now)
        variant = entity_service.resolve_variant(session, row, product, institution, outlet)

        if variant.id in seen_variants:
            session.add(
                ReviewItem(
                    run_id=run.id,
                    entity_type="variant",
                    entity_id=variant.id,
                    issue_type="duplicate",
                    severity="warning",
                    message=f"같은 실행에서 비교 단위가 중복됐다: {row.source_row_ref}",
                    payload_json={"source_row_ref": row.source_row_ref},
                    created_at=now,
                )
            )
            continue
        seen_variants.add(variant.id)

        session.add(
            RateObservation(
                variant_id=variant.id,
                run_id=run.id,
                raw_artifact_id=artifact.id,
                as_of=row.source_effective_at,
                observed_at=now,
                base_rate=row.base_rate,
                max_rate=row.max_rate,
                source_detail_json=row.extra,
                raw_preference_text=row.preference_raw,
                validation_status=row.validation_status,
                validation_message=row.validation_message,
                content_hash=_content_hash(row),
                base_source_locator=row.base_source_locator,
                option_source_locator=row.option_source_locator,
                source_record_hash=row.source_record_hash,
                source_effective_at=row.source_effective_at,
            )
        )

        if row.validation_status == ValidationStatus.ERROR:
            errors += 1
            session.add(
                ReviewItem(
                    run_id=run.id,
                    entity_type="variant",
                    entity_id=variant.id,
                    issue_type="parse_error",
                    severity="error",
                    message=row.validation_message or "파싱 오류",
                    payload_json={"source_row_ref": row.source_row_ref},
                    created_at=now,
                )
            )
        else:
            valid += 1

    session.flush()
    return valid, errors


def ensure_source(session: Session, adapter, now: datetime) -> Source:  # noqa: ANN001
    """수집원 행을 찾거나 만든다.

    모든 값을 어댑터에서 읽는다. 예전에는 finlife 값이 여기 하드코딩돼 있어
    다른 원천으로 돌리면 이름이 "금융감독원…"이고 `policy_status`가
    `allowed`인 잘못된 행이 생겼다. 특히 `policy_status`는 원천마다 다르고
    (새마을금고는 약관 미확인이라 `review`) 틀리면 안 되는 값이다.
    """
    source = session.get(Source, adapter.source_id)
    if source is not None:
        return source
    source = Source(
        id=adapter.source_id,
        name=adapter.source_name,
        sector=adapter.sector,
        mode=adapter.mode,
        source_role=adapter.source_role,
        trust_level=adapter.trust_level,
        priority=adapter.priority,
        base_reference=adapter.base_reference,
        enabled=True,
        policy_status=adapter.policy_status,
        coverage_status=adapter.coverage_status,
        created_at=now,
        updated_at=now,
    )
    session.add(source)
    session.flush()
    return source


async def collect_source(
    adapter,  # noqa: ANN001 — SourceAdapter 프로토콜
    request: CollectionRequest,
    factory: sessionmaker[Session],
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
) -> CollectionRunResult:
    """한 수집원을 끝까지 실행한다.

    fetch가 실패하면 관측값을 하나도 쓰지 않고 실행 상태만 남긴다. 이전
    정상값은 그대로 유지된다 (v3 §10.3).

    파싱·저장 중 실패도 예외를 밖으로 던지지 않고 실행 상태로 돌려준다.
    HTML을 긁는 수집원에서는 구조 변경이 주된 실패 모드라, 예외가 호출자까지
    올라가면 CLI가 traceback으로 죽고 실행 이력만 남는다.
    """
    now = _utcnow()
    run_id = _new_run(factory, adapter, request, now)

    try:
        artifacts = await adapter.fetch(request)
    except SourceBlockedError as exc:
        _finalize_failure(factory, run_id, RunStatus.BLOCKED, str(exc))
        return CollectionRunResult(run_id, RunStatus.BLOCKED, 0, 0, 0, 0, 0, str(exc))
    except SchemaChangedError as exc:
        _finalize_failure(factory, run_id, RunStatus.SCHEMA_CHANGED, str(exc))
        return CollectionRunResult(run_id, RunStatus.SCHEMA_CHANGED, 0, 0, 0, 0, 0, str(exc))
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 실행 이력에 남긴다
        _finalize_failure(factory, run_id, RunStatus.FAILED, f"{type(exc).__name__}: {exc}")
        return CollectionRunResult(run_id, RunStatus.FAILED, 0, 0, 0, 0, 0, str(exc))

    return _process(adapter, artifacts, factory, run_id, raw_root, now)


def _new_run(
    factory: sessionmaker[Session],
    adapter,  # noqa: ANN001
    request: CollectionRequest,
    now: datetime,
) -> str:
    with session_scope(factory) as session:
        ensure_source(session, adapter, now)
        run = CollectionRun(
            source_id=adapter.source_id,
            mode=adapter.mode,
            started_at=now,
            status=RunStatus.RUNNING,
            query_context_json={
                "regions": list(request.regions),
                "options": {k: list(v) if isinstance(v, tuple) else v
                            for k, v in request.options.items()},
            },
        )
        session.add(run)
        session.flush()
        return run.id


# 이 비율을 넘으면 원천 구조가 바뀐 것으로 보고 실행을 멈춘다.
#
# 한 장이 어긋나는 것은 그 금고가 그 상품군을 안 팔거나 일시적 오류 응답을
# 준 것이다. 여러 장이 한꺼번에 어긋나면 우리 파서가 틀린 것이다.
SCHEMA_FAIL_RATIO = 0.05
# 표본이 적을 때는 비율이 쉽게 튄다. 아티팩트가 이보다 적으면 한 장만
# 어긋나도 멈춘다 — 예전 동작 그대로다.
SCHEMA_FAIL_MIN_SAMPLE = 20


def _schema_change_is_systemic(
    failures: list[tuple[str, str]], artifacts: list[RawArtifactData]
) -> bool:
    """구조 어긋남이 원천 전체의 변화인지, 페이지 하나의 사정인지.

    >>> a = [None] * 100
    >>> _schema_change_is_systemic([("x", "e")], a)
    False
    >>> _schema_change_is_systemic([("x", "e")] * 6, a)
    True

    표본이 적으면 한 장도 그냥 넘기지 않는다.

    >>> _schema_change_is_systemic([("x", "e")], [None] * 3)
    True
    """
    if not failures:
        return False
    if len(artifacts) < SCHEMA_FAIL_MIN_SAMPLE:
        return True
    return len(failures) / len(artifacts) > SCHEMA_FAIL_RATIO


def _process(
    adapter,  # noqa: ANN001
    artifacts: list[RawArtifactData],
    factory: sessionmaker[Session],
    run_id: str,
    raw_root: Path,
    now: datetime,
) -> CollectionRunResult:
    try:
        with session_scope(factory) as session:
            run = session.get(CollectionRun, run_id)
            saved = save_raw_artifacts(session, run, artifacts, raw_root, now)

            parsed = valid = errors = 0
            warnings: list[str] = []
            # 구조가 어긋난 페이지. 한 장 때문에 실행 전체를 버리지 않는다.
            #
            # 2026-08-05 전국 수집(2,520장)에서 한 장이 SchemaChangedError를
            # 냈고, 그 예외가 트랜잭션 밖으로 나가면서 **2시간치 원본이 통째로
            # 롤백**됐다. raw_count가 0으로 남아 어느 금고의 어떤 페이지였는지
            # 조차 알 수 없게 됐다.
            #
            # 이제는 페이지마다 잡아 검수항목으로 남기고 계속 간다. 다만
            # 명세서 v3.1 §8의 "구조 변경은 멈춘다"를 버리는 것은 아니다 —
            # 어긋난 비율이 임계를 넘으면 그때 실행을 schema_changed로 끝낸다.
            # 한 장은 그 원천의 사정이고, 여러 장은 우리 파서가 틀린 것이다.
            schema_failures: list[tuple[str, str]] = []
            # 실행 단위로 유지한다. 페이지마다 초기화하면 페이지 경계를 넘는
            # 중복을 놓쳐 (variant_id, run_id) 유니크 제약에 걸린다.
            seen_variants: set[str] = set()
            for artifact_data, artifact_row in zip(artifacts, saved, strict=True):
                try:
                    rows, page_warnings = adapter.parse_with_warnings(artifact_data)
                except SchemaChangedError as exc:
                    schema_failures.append((artifact_data.filename, str(exc)))
                    continue
                warnings.extend(page_warnings)
                parsed += len(rows)
                page_valid, page_errors = persist_rows(
                    session, run, rows, artifact_row, now, seen_variants
                )
                valid += page_valid
                errors += page_errors

            for filename, message in schema_failures:
                session.add(
                    ReviewItem(
                        run_id=run.id,
                        issue_type="schema_changed",
                        severity="error",
                        message=f"{filename}: {message}",
                        payload_json={"filename": filename},
                        created_at=now,
                    )
                )
            if _schema_change_is_systemic(schema_failures, artifacts):
                raise SchemaChangedError(
                    f"{len(schema_failures)}/{len(artifacts)}장이 구조와 어긋난다:"
                    f" {schema_failures[0][1]}"
                )

            for warning in warnings:
                session.add(
                    ReviewItem(
                        run_id=run.id,
                        issue_type="schema_warning",
                        severity="warning",
                        message=warning,
                        payload_json={},
                        created_at=now,
                    )
                )

            # 구조가 어긋나 건너뛴 페이지가 있으면 success가 아니다.
            # 조용히 success로 끝나면 그 금고가 통째로 빠진 것을 아무도 모른다.
            complete = errors == 0 and not schema_failures
            run.status = RunStatus.SUCCESS if complete else RunStatus.PARTIAL
            run.finished_at = _utcnow()
            run.raw_count = len(artifacts)
            run.parsed_count = parsed
            run.valid_count = valid
            run.warning_count = len(warnings)
            run.error_count = errors
            run.schema_fingerprint = artifacts[0].schema_fingerprint if artifacts else None
            skipped = (
                f", 구조 어긋나 건너뜀 {len(schema_failures)}장" if schema_failures else ""
            )
            run.message = (
                f"{len(artifacts)}개 원본에서 {parsed}행 파싱,"
                f" 정상 {valid}, 오류 {errors}{skipped}"
            )
            result = CollectionRunResult(
                run_id, run.status, len(artifacts), parsed, valid, len(warnings), errors,
                run.message,
            )
        return result
    except SchemaChangedError as exc:
        _finalize_failure(factory, run_id, RunStatus.SCHEMA_CHANGED, str(exc))
        return CollectionRunResult(
            run_id, RunStatus.SCHEMA_CHANGED, len(artifacts), 0, 0, 0, 0, str(exc)
        )
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 실행 이력에 남긴다
        _finalize_failure(factory, run_id, RunStatus.FAILED, f"{type(exc).__name__}: {exc}")
        return CollectionRunResult(
            run_id, RunStatus.FAILED, len(artifacts), 0, 0, 0, 0, str(exc)
        )


def _finalize_failure(
    factory: sessionmaker[Session], run_id: str, status: str, message: str
) -> None:
    """실행 상태만 기록한다. 관측값은 쓰지 않는다."""
    with session_scope(factory) as session:
        run = session.get(CollectionRun, run_id)
        if run is None:
            return
        run.status = status
        run.finished_at = _utcnow()
        run.message = message[:2000]
