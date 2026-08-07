"""수집 오케스트레이션 (명세서 v3 §10.1).

    create_run → fetch → save_raw → parse → normalize → resolve
              → validate → persist → finalize

실패한 실행이 최신 정상값을 대체하지 않게 트랜잭션 경계를 지킨다 (v3 §10.3).
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from rate_monitor.collectors.base import SchemaChangedError, SourceBlockedError
from rate_monitor.db.models import (
    CollectionRun,
    CollectionRunStat,
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

    # 돌려주는 목록은 `artifacts`와 **1:1로 맞춘다.** 호출하는 쪽이
    # `zip(artifacts, saved, strict=True)`로 원본과 파싱 결과를 짝지으므로,
    # 하나라도 빠지면 그 조회가 통째로 사라진다.
    #
    # ── 바이트가 같은 응답을 어떻게 다루나 ────────────────────────
    #
    # `raw_artifacts`에 `UNIQUE(run_id, sha256)`이 있다. 그런데 새마을금고·
    # 농·축협 금리 화면에는 금고 이름도 주소도 없어서, 취급 상품과 금리가
    # 같은 두 금고는 응답이 완전히 같아진다.
    #
    # 예전에는 **수집기가** 그 응답을 통째로 버려서 제약을 피했다. 그래서
    # 뒤에 온 금고가 DB에 아예 안 생겼다 — 2026-08-06 실행에서 경남 186장,
    # 관측 7,274건이 그렇게 사라졌는데 오류도 경고도 0이었다.
    #
    # 이제 버리지 않는다. **파일은 조회마다 쓰고**(원본 증거는 조회 단위로
    # 남는다), DB 행만 같은 바이트끼리 공유한다. 파싱은 메모리의
    # `RawArtifactData`로 하므로 금고별 맥락(`request_meta`)이 정확히
    # 유지되고, 관측은 자기 내용을 담은 원본 행을 가리킨다.
    #
    # 공유된 행에는 **함께 가리키는 조회를 전부 적는다** (`shared_with`).
    # 안 적으면 그 행이 첫 조회만 가리켜서, 뒤엣 금고의 관측이 남의 이름을 단
    # 원본을 가리키게 된다 — 추적이 바로 이 사고의 경우에만 끊긴다.
    saved: list[RawArtifact] = []
    by_digest: dict[str, RawArtifact] = {}
    for artifact in artifacts:
        path = day_dir / artifact.filename
        path.write_bytes(artifact.content)
        digest = hashlib.sha256(artifact.content).hexdigest()

        shared = by_digest.get(digest)
        if shared is not None:
            # JSON 칸은 제자리 수정이 SQLAlchemy에 안 잡힌다. 새 dict를 넣는다.
            meta = dict(shared.request_meta_json)
            meta["shared_with"] = [*meta.get("shared_with", []), artifact.filename]
            shared.request_meta_json = meta
            saved.append(shared)
            continue

        record = RawArtifact(
            run_id=run.id,
            artifact_type=artifact.artifact_type,
            relative_path=str(path),
            sha256=digest,
            content_length=len(artifact.content),
            encoding="utf-8",
            request_meta_json=artifact.request_meta,
            captured_at=now,
        )
        session.add(record)
        by_digest[digest] = record
        saved.append(record)
    session.flush()
    return saved


@dataclass
class ChangeTally:
    """이번 실행이 관측에 무엇을 했는가 (선행 수정안 §3.2).

    `parsed_count`만으로는 4,010행을 받고 관측이 안 늘어난 것이 실패인지
    "아무것도 안 바뀐 것"인지 알 수 없다. 여기서 갈라 센다.
    """

    unchanged: int = 0
    changed: int = 0
    new_variants: int = 0


def _record_observation(
    session: Session,
    run: CollectionRun,
    row: ParsedRateRow,
    variant_id: str,
    artifact: RawArtifact,
    now: datetime,
    tally: ChangeTally,
) -> None:
    """값이 바뀌었을 때만 새 관측을 만든다 (선행 수정안 §3.2).

    같으면  → 행을 만들지 않고 last_seen_at·seen_count·last_run_id만 갱신
    다르면  → 살아 있던 행에 valid_to를 찍고 새 행을 만든다
    """
    content_hash = _content_hash(row)
    current = session.scalar(
        select(RateObservation).where(
            RateObservation.variant_id == variant_id,
            RateObservation.valid_to.is_(None),
        )
    )

    if current is not None and current.content_hash == content_hash:
        current.last_seen_at = now
        current.seen_count += 1
        current.last_run_id = run.id
        # 원천 기준일은 값이 같아도 움직일 수 있다. 최신을 남긴다.
        current.as_of = row.source_effective_at
        current.source_effective_at = row.source_effective_at
        tally.unchanged += 1
        return

    if current is None:
        tally.new_variants += 1
    else:
        # 옛 값을 지우지 않는다. 언제까지 그 값이었는지가 이력이다.
        current.valid_to = now
        tally.changed += 1

    session.add(
        RateObservation(
            variant_id=variant_id,
            run_id=run.id,
            last_run_id=run.id,
            raw_artifact_id=artifact.id,
            as_of=row.source_effective_at,
            observed_at=now,
            first_seen_at=now,
            last_seen_at=now,
            seen_count=1,
            valid_from=now,
            valid_to=None,
            base_rate=row.base_rate,
            max_rate=row.max_rate,
            source_detail_json=row.extra,
            raw_preference_text=row.preference_raw,
            validation_status=row.validation_status,
            validation_message=row.validation_message,
            content_hash=content_hash,
            base_source_locator=row.base_source_locator,
            option_source_locator=row.option_source_locator,
            source_record_hash=row.source_record_hash,
            source_effective_at=row.source_effective_at,
        )
    )


def persist_rows(
    session: Session,
    run: CollectionRun,
    rows: list[ParsedRateRow],
    artifact: RawArtifact,
    now: datetime,
    seen_variants: set[str],
    tally: ChangeTally | None = None,
) -> tuple[int, int]:
    """표준 행을 저장한다. (정상 건수, 오류 건수)를 돌려준다.

    **값이 바뀔 때만 새 관측을 만든다** (선행 수정안 §3.2). 직전 값과
    `content_hash`가 같으면 행을 만들지 않고 `last_seen_at`·`seen_count`·
    `last_run_id`만 갱신한다. 예전에는 수집할 때마다 새 행이 생겨 같은
    3.10%가 날짜마다 한 줄씩 쌓였다 — 실측 185,923행 중 43,116행이 그것이고,
    평일 수집으로 1년을 돌면 약 19 GB가 된다.

    같은 실행 안에서 같은 비교 단위가 두 번 나오면 뒤엣것을 버리고 검수항목을
    남긴다. 살아 있는 관측이 비교 단위마다 하나뿐이라는 부분 유니크 인덱스를
    미리 지킨다.

    `seen_variants`는 호출자가 실행 단위로 넘긴다. 아티팩트(페이지)마다
    새로 만들면 페이지 경계를 넘는 중복을 놓친다.
    """
    valid = 0
    errors = 0
    tally = tally if tally is not None else ChangeTally()

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

        _record_observation(session, run, row, variant.id, artifact, now, tally)

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
            tally = ChangeTally()
            for artifact_data, artifact_row in zip(artifacts, saved, strict=True):
                try:
                    rows, page_warnings = adapter.parse_with_warnings(artifact_data)
                except SchemaChangedError as exc:
                    schema_failures.append((artifact_data.filename, str(exc)))
                    continue
                warnings.extend(page_warnings)
                parsed += len(rows)
                page_valid, page_errors = persist_rows(
                    session, run, rows, artifact_row, now, seen_variants, tally
                )
                valid += page_valid
                errors += page_errors

            # 원천이 조회를 무시하고 같은 답을 되풀이했다.
            #
            # **받은 것은 그대로 저장한다.** 두 시간을 받고 나서 통째로 버리면
            # 원래 고치려던 손실과 같은 일이 된다. 대신 실행을 성공으로
            # 끝내지 않고 검수항목을 남긴다 — 경남이 사라졌을 때 없던 것이
            # 바로 이것이다.
            alert = getattr(adapter, "fetch_alert", "")
            if alert:
                session.add(
                    ReviewItem(
                        run_id=run.id,
                        issue_type="repeated_response",
                        severity="error",
                        message=alert,
                        payload_json={"source_id": adapter.source_id},
                        created_at=now,
                    )
                )

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
            #
            # 응답 되풀이도 마찬가지다. 경남 186장이 사라진 실행은 오류 0으로
            # 끝났고, 상태도 검수항목도 그 사실을 말하지 않았다.
            complete = errors == 0 and not schema_failures and not alert
            run.status = RunStatus.SUCCESS if complete else RunStatus.PARTIAL
            run.finished_at = _utcnow()
            run.raw_count = len(artifacts)
            run.parsed_count = parsed
            run.valid_count = valid
            run.warning_count = len(warnings)
            run.error_count = errors
            run.schema_fingerprint = artifacts[0].schema_fingerprint if artifacts else None

            # 실행별 품질·건수 (선행 수정안 §3.2).
            #
            # parsed_count만 보면 4,010행을 받고 관측이 안 늘어난 것이 실패인지
            # "아무것도 안 바뀐 것"인지 알 수 없다. 여기서 갈라 남긴다.
            session.add(
                CollectionRunStat(
                    run_id=run.id,
                    source_id=run.source_id,
                    fetched_count=len(artifacts),
                    parsed_count=parsed,
                    unchanged_count=tally.unchanged,
                    changed_count=tally.changed,
                    new_variant_count=tally.new_variants,
                    # 직전 실행에 있었는데 이번에 안 온 비교 단위는 아직 세지
                    # 않는다. 부산만 돌린 실행이 전국 단위를 "사라졌다"고
                    # 셀 수 있어서다 — 원천별 범위를 알기 전에는 0으로 둔다.
                    missing_variant_count=0,
                    error_count=errors,
                    created_at=now,
                )
            )
            skipped = (
                f", 구조 어긋나 건너뜀 {len(schema_failures)}장" if schema_failures else ""
            )
            # 어댑터가 응답 되풀이를 봤으면 그 요약도 남긴다. **0건이어도
            # 적는다** — 안 적으면 "검사를 안 했나"와 "검사했는데 0이었나"를
            # 구별할 수 없다. 경남 186장이 사라졌을 때 흔적이 정확히 0이었다.
            repeats = getattr(adapter, "fetch_note", "")
            run.message = (
                f"{len(artifacts)}개 원본에서 {parsed}행 파싱,"
                f" 정상 {valid}, 오류 {errors}{skipped}"
                + (f" · {repeats}" if repeats else "")
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
