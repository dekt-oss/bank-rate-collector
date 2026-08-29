from pathlib import Path


funding_path = Path("src/rate_monitor/collectors/cu/funding.py")
test_path = Path("tests/test_cu_funding.py")
funding = funding_path.read_text(encoding="utf-8")
tests = test_path.read_text(encoding="utf-8")
changed = False

old = '''@dataclass(frozen=True)
class CuFundingCollectionResult:
    status: str
    run_id: str
    target_count: int
    completed_targets: int
    failed_targets: tuple[str, ...]
    fetched_artifacts: int
    parsed_points: int
    stored: int
    unchanged: int
    revisions: int
    message: str
'''
new = '''@dataclass(frozen=True)
class CuFundingCollectionResult:
    status: str
    run_id: str
    target_count: int
    completed_targets: int
    failed_targets: tuple[str, ...]
    fetched_artifacts: int
    parsed_points: int
    stored: int
    unchanged: int
    revisions: int
    warning_count: int
    message: str
'''
if old in funding:
    funding = funding.replace(old, new, 1)
    changed = True
elif new not in funding:
    raise SystemExit("CuFundingCollectionResult block mismatch")

old = '''def _record_from_row(row: dict[str, Any], expected_cu: str) -> DisclosureRecord | None:
    cu_ingno = str(row.get("cuIngno") or "").strip()
    if cu_ingno != expected_cu:
        raise CuFundingContractError(
            f"신협 공시목록 identity 불일치: requested={expected_cu} returned={cu_ingno!r}"
        )
    disclosure_type = str(row.get("disclosureTy") or "").strip()
    if disclosure_type not in {"1", "2"}:
        return None
    if str(row.get("bogoTy") or "").strip() != "Y":
        return None
    if str(row.get("chkYn3") or "").strip() != "Y":
        return None
    short_file_name = str(row.get("shortFileName") or "").strip()
    if not short_file_name:
        return None
    name = str(row.get("disclosureName") or "").strip()
    match = _YEAR.search(name)
    if match is None:
        raise CuFundingContractError(f"공시명에서 연도를 읽을 수 없다: {name!r}")
    year = int(match.group(1))
    month = 12 if disclosure_type == "1" else 6
    raw_no = str(row.get("disclosureNo") or "").strip()
    if not raw_no.isdigit():
        raise CuFundingContractError(f"disclosureNo 형식 오류: {raw_no!r}")
    return DisclosureRecord(
        cu_ingno=cu_ingno,
        disclosure_no=int(raw_no),
        disclosure_type=disclosure_type,
        disclosure_name=name,
        reg_date=str(row.get("regDate") or "").strip(),
        short_file_name=short_file_name,
        year=year,
        month=month,
    )


def select_latest_disclosures(
    rows: list[dict[str, Any]],
    *,
    cu_ingno: str,
    periods: int,
) -> list[DisclosureRecord]:
    """정기/반기 요약공시를 reporting period별 한 건으로 결정론적으로 고른다."""
    if periods < 1:
        raise ValueError("periods는 1 이상이어야 한다")
    candidates = [
        record
        for row in rows
        if (record := _record_from_row(row, cu_ingno)) is not None
    ]
    by_period: dict[str, DisclosureRecord] = {}
    for record in candidates:
        prior = by_period.get(record.source_effective_month)
        if prior is None or record.disclosure_no > prior.disclosure_no:
            by_period[record.source_effective_month] = record
    return sorted(
        by_period.values(),
        key=lambda record: (record.year, record.month, record.disclosure_no),
        reverse=True,
    )[:periods]
'''
new = '''def _report_row_meta(
    row: dict[str, Any], expected_cu: str
) -> tuple[int, str, str, str, str] | None:
    cu_ingno = str(row.get("cuIngno") or "").strip()
    if cu_ingno != expected_cu:
        raise CuFundingContractError(
            f"신협 공시목록 identity 불일치: requested={expected_cu} returned={cu_ingno!r}"
        )
    disclosure_type = str(row.get("disclosureTy") or "").strip()
    if disclosure_type not in {"1", "2"}:
        return None
    if str(row.get("bogoTy") or "").strip() != "Y":
        return None
    if str(row.get("chkYn3") or "").strip() != "Y":
        return None
    short_file_name = str(row.get("shortFileName") or "").strip()
    if not short_file_name:
        return None
    raw_no = str(row.get("disclosureNo") or "").strip()
    if not raw_no.isdigit():
        raise CuFundingContractError(f"disclosureNo 형식 오류: {raw_no!r}")
    return (
        int(raw_no),
        disclosure_type,
        str(row.get("disclosureName") or "").strip(),
        str(row.get("regDate") or "").strip(),
        short_file_name,
    )


def _record_from_meta(
    *,
    cu_ingno: str,
    disclosure_no: int,
    disclosure_type: str,
    disclosure_name: str,
    reg_date: str,
    short_file_name: str,
) -> DisclosureRecord:
    match = _YEAR.search(disclosure_name)
    if match is None:
        raise CuFundingContractError(
            f"공시명에서 연도를 읽을 수 없다: {disclosure_name!r}"
        )
    year = int(match.group(1))
    return DisclosureRecord(
        cu_ingno=cu_ingno,
        disclosure_no=disclosure_no,
        disclosure_type=disclosure_type,
        disclosure_name=disclosure_name,
        reg_date=reg_date,
        short_file_name=short_file_name,
        year=year,
        month=12 if disclosure_type == "1" else 6,
    )


def _record_from_row(row: dict[str, Any], expected_cu: str) -> DisclosureRecord | None:
    meta = _report_row_meta(row, expected_cu)
    if meta is None:
        return None
    return _record_from_meta(
        cu_ingno=expected_cu,
        disclosure_no=meta[0],
        disclosure_type=meta[1],
        disclosure_name=meta[2],
        reg_date=meta[3],
        short_file_name=meta[4],
    )


def _select_latest_disclosures_with_warnings(
    rows: list[dict[str, Any]],
    *,
    cu_ingno: str,
    periods: int,
) -> tuple[list[DisclosureRecord], list[str]]:
    """검증 가능한 공시는 선택하고 오래된 연도불명 행만 evidence로 격리한다."""
    if periods < 1:
        raise ValueError("periods는 1 이상이어야 한다")

    candidates: list[DisclosureRecord] = []
    ambiguous: list[tuple[int, str, str]] = []
    for row in rows:
        meta = _report_row_meta(row, cu_ingno)
        if meta is None:
            continue
        disclosure_no, disclosure_type, name, reg_date, short_file_name = meta
        if _YEAR.search(name) is None:
            ambiguous.append((disclosure_no, name, reg_date))
            continue
        candidates.append(
            _record_from_meta(
                cu_ingno=cu_ingno,
                disclosure_no=disclosure_no,
                disclosure_type=disclosure_type,
                disclosure_name=name,
                reg_date=reg_date,
                short_file_name=short_file_name,
            )
        )

    if not candidates:
        if ambiguous:
            raise CuFundingContractError(
                f"검증 가능한 연도 공시가 없고 연도불명 행만 있다: cuIngno={cu_ingno}"
            )
        return [], []

    newest_explicit_reg_date = max(record.reg_date for record in candidates)
    warnings: list[str] = []
    for disclosure_no, name, reg_date in ambiguous:
        if not reg_date or reg_date >= newest_explicit_reg_date:
            raise CuFundingContractError(
                "최신권 공시의 연도를 검증할 수 없다: "
                f"cuIngno={cu_ingno} disclosureNo={disclosure_no} "
                f"regDate={reg_date!r} name={name!r}"
            )
        warnings.append(
            "historical disclosure quarantined: missing explicit year "
            f"cuIngno={cu_ingno} disclosureNo={disclosure_no} "
            f"regDate={reg_date} name={name!r}"
        )

    by_period: dict[str, DisclosureRecord] = {}
    for record in candidates:
        prior = by_period.get(record.source_effective_month)
        if prior is None or record.disclosure_no > prior.disclosure_no:
            by_period[record.source_effective_month] = record
    selected = sorted(
        by_period.values(),
        key=lambda record: (record.year, record.month, record.disclosure_no),
        reverse=True,
    )[:periods]
    return selected, warnings


def select_latest_disclosures(
    rows: list[dict[str, Any]],
    *,
    cu_ingno: str,
    periods: int,
) -> list[DisclosureRecord]:
    """정기/반기 요약공시를 reporting period별 한 건으로 결정론적으로 고른다."""
    selected, _warnings = _select_latest_disclosures_with_warnings(
        rows,
        cu_ingno=cu_ingno,
        periods=periods,
    )
    return selected
'''
if old in funding:
    funding = funding.replace(old, new, 1)
    changed = True
elif new not in funding:
    raise SystemExit("disclosure selection block mismatch")

anchor = '''def _list_rows(payload: Any) -> list[dict[str, Any]]:
'''
helper = '''def _parse_summary_with_history_policy(
    text: str,
    *,
    disclosure: DisclosureRecord,
    institution_id: str,
    institution_name: str,
    source_locator: str,
    is_latest: bool,
) -> tuple[CuFundingPoint | None, str | None]:
    try:
        return (
            parse_summary_point(
                text,
                disclosure=disclosure,
                institution_id=institution_id,
                institution_name=institution_name,
                source_locator=source_locator,
            ),
            None,
        )
    except CuFundingContractError as exc:
        if is_latest:
            raise
        return (
            None,
            "historical disclosure quarantined: summary contract mismatch "
            f"cuIngno={disclosure.cu_ingno} disclosureNo={disclosure.disclosure_no} "
            f"claimedMonth={disclosure.source_effective_month} reason={exc}",
        )


'''
if helper not in funding:
    if anchor not in funding:
        raise SystemExit("summary policy insertion anchor missing")
    funding = funding.replace(anchor, helper + anchor, 1)
    changed = True

old = '''def _fetch_target(
    client: httpx.Client,
    *,
    cu_ingno: str,
    institution_id: str,
    institution_name: str,
    periods: int,
    request_interval: float,
) -> tuple[list[CuFundingPoint], list[RawArtifactData], dict[int, int]]:
    rows, artifacts = _fetch_disclosure_rows(
        client,
        cu_ingno=cu_ingno,
        periods=periods,
        request_interval=request_interval,
    )
    disclosures = select_latest_disclosures(
        rows,
        cu_ingno=cu_ingno,
        periods=periods,
    )
    if not disclosures:
        raise CuFundingContractError(f"정기/반기 요약공시가 없다: cuIngno={cu_ingno}")

    points: list[CuFundingPoint] = []
    summary_artifact_index: dict[int, int] = {}
    for disclosure in disclosures:
        if request_interval:
            time.sleep(request_interval)
        url = _summary_url(disclosure)
        response = client.get(url)
        response.raise_for_status()
        raw = response.content
        point = parse_summary_point(
            response.text,
            disclosure=disclosure,
            institution_id=institution_id,
            institution_name=institution_name,
            source_locator=url,
        )
        summary_artifact_index[disclosure.disclosure_no] = len(artifacts)
        artifacts.append(
            _artifact(
                content=raw,
                filename=(
                    f"cu-funding-{cu_ingno}-{point.source_effective_month}-"
                    f"{disclosure.disclosure_no}.html"
                ),
                request_meta={
                    "kind": "summary_disclosure",
                    "cuIngno": cu_ingno,
                    "disclosure_no": disclosure.disclosure_no,
                    "disclosure_type": disclosure.disclosure_type,
                    "source_effective_month": point.source_effective_month,
                    "endpoint": url,
                },
                artifact_type="html",
            )
        )
        points.append(point)
    return points, artifacts, summary_artifact_index
'''
new = '''def _fetch_target(
    client: httpx.Client,
    *,
    cu_ingno: str,
    institution_id: str,
    institution_name: str,
    periods: int,
    request_interval: float,
) -> tuple[list[CuFundingPoint], list[RawArtifactData], dict[int, int], list[str]]:
    rows, artifacts = _fetch_disclosure_rows(
        client,
        cu_ingno=cu_ingno,
        periods=periods,
        request_interval=request_interval,
    )
    disclosures, warnings = _select_latest_disclosures_with_warnings(
        rows,
        cu_ingno=cu_ingno,
        periods=periods,
    )
    if not disclosures:
        raise CuFundingContractError(f"정기/반기 요약공시가 없다: cuIngno={cu_ingno}")

    points: list[CuFundingPoint] = []
    summary_artifact_index: dict[int, int] = {}
    for index, disclosure in enumerate(disclosures):
        if request_interval:
            time.sleep(request_interval)
        url = _summary_url(disclosure)
        response = client.get(url)
        response.raise_for_status()
        raw = response.content
        point, warning = _parse_summary_with_history_policy(
            response.text,
            disclosure=disclosure,
            institution_id=institution_id,
            institution_name=institution_name,
            source_locator=url,
            is_latest=index == 0,
        )
        artifact_index = len(artifacts)
        request_meta: dict[str, Any] = {
            "kind": "summary_disclosure",
            "cuIngno": cu_ingno,
            "disclosure_no": disclosure.disclosure_no,
            "disclosure_type": disclosure.disclosure_type,
            "source_effective_month": disclosure.source_effective_month,
            "endpoint": url,
        }
        if warning is not None:
            request_meta["quarantined"] = True
            request_meta["quarantine_reason"] = warning
        artifacts.append(
            _artifact(
                content=raw,
                filename=(
                    f"cu-funding-{cu_ingno}-{disclosure.source_effective_month}-"
                    f"{disclosure.disclosure_no}.html"
                ),
                request_meta=request_meta,
                artifact_type="html",
            )
        )
        if warning is not None:
            warnings.append(warning)
            continue
        if point is None:
            raise CuFundingContractError(
                "summary policy가 point와 warning을 모두 반환하지 않았다"
            )
        summary_artifact_index[disclosure.disclosure_no] = artifact_index
        points.append(point)
    if not points:
        raise CuFundingContractError(
            f"검증 가능한 예수부채 observation이 없다: cuIngno={cu_ingno}"
        )
    return points, artifacts, summary_artifact_index, warnings
'''
if old in funding:
    funding = funding.replace(old, new, 1)
    changed = True
elif new not in funding:
    raise SystemExit("_fetch_target block mismatch")

old = '''    fetched = parsed = stored = unchanged = revisions = 0
    completed = 0
    failures: dict[str, str] = {}
'''
new = '''    fetched = parsed = stored = unchanged = revisions = 0
    warning_count = 0
    completed = 0
    failures: dict[str, str] = {}
'''
if old in funding:
    funding = funding.replace(old, new, 1)
    changed = True
elif new not in funding:
    raise SystemExit("collector counters block mismatch")

old = '''                points, artifacts, summary_index = _fetch_target(
'''
new = '''                points, artifacts, summary_index, target_warnings = _fetch_target(
'''
if old in funding:
    funding = funding.replace(old, new, 1)
    changed = True
elif new not in funding:
    raise SystemExit("_fetch_target unpack mismatch")

old = '''                fetched += len(artifacts)
                parsed += len(points)
                completed += 1
'''
new = '''                fetched += len(artifacts)
                parsed += len(points)
                warning_count += len(target_warnings)
                for warning in target_warnings:
                    print(f"CU funding warning: {warning}", flush=True)
                completed += 1
'''
if old in funding:
    funding = funding.replace(old, new, 1)
    changed = True
elif new not in funding:
    raise SystemExit("collector target accounting mismatch")

old = '''    message = (
        f"targets={completed}/{len(targets)} points={parsed} stored={stored} "
        f"revisions={revisions} unchanged={unchanged} failures={len(failures)}"
    )
'''
new = '''    message = (
        f"targets={completed}/{len(targets)} points={parsed} stored={stored} "
        f"revisions={revisions} unchanged={unchanged} warnings={warning_count} "
        f"failures={len(failures)}"
    )
'''
if old in funding:
    funding = funding.replace(old, new, 1)
    changed = True
elif new not in funding:
    raise SystemExit("collector message mismatch")

old = '''        run.error_count = len(failures)
        run.message = message[:500]
'''
new = '''        run.warning_count = warning_count
        run.error_count = len(failures)
        run.message = message[:500]
'''
if old in funding:
    funding = funding.replace(old, new, 1)
    changed = True
elif new not in funding:
    raise SystemExit("run warning_count insertion mismatch")

old = '''        revisions=revisions,
        message=message,
'''
new = '''        revisions=revisions,
        warning_count=warning_count,
        message=message,
'''
if old in funding:
    funding = funding.replace(old, new, 1)
    changed = True
elif new not in funding:
    raise SystemExit("result warning_count insertion mismatch")

old = '''    disclosure_name: str,
    bogo_ty: str = "Y",
) -> dict[str, object]:
'''
new = '''    disclosure_name: str,
    bogo_ty: str = "Y",
    reg_date: str = "2026-02-01",
) -> dict[str, object]:
'''
if old in tests:
    tests = tests.replace(old, new, 1)
    changed = True
elif new not in tests:
    raise SystemExit("test _list_row signature mismatch")

old = '''        "regDate": "2026-02-01",
'''
new = '''        "regDate": reg_date,
'''
if old in tests:
    tests = tests.replace(old, new, 1)
    changed = True
elif new not in tests:
    raise SystemExit("test _list_row regDate mismatch")

old = '''    _ensure_source,
    _targets,
    _upsert_point,
'''
new = '''    _ensure_source,
    _parse_summary_with_history_policy,
    _select_latest_disclosures_with_warnings,
    _targets,
    _upsert_point,
'''
if old in tests:
    tests = tests.replace(old, new, 1)
    changed = True
elif new not in tests:
    raise SystemExit("test imports mismatch")

anchor = '''def _source(source_id: str, now: datetime) -> m.Source:
'''
extra_tests = '''def test_historical_missing_year_row_is_quarantined() -> None:
    rows = [
        _list_row(
            disclosure_no=25111,
            disclosure_type="2",
            disclosure_name="2026년도 상반기 경영공시",
            reg_date="2026-08-21",
        ),
        _list_row(
            disclosure_no=7658,
            disclosure_type="2",
            disclosure_name="상반기결산공시",
            reg_date="2021-09-09",
        ),
    ]

    selected, warnings = _select_latest_disclosures_with_warnings(
        rows,
        cu_ingno="02002",
        periods=12,
    )

    assert [item.disclosure_no for item in selected] == [25111]
    assert len(warnings) == 1
    assert "7658" in warnings[0]
    assert "missing explicit year" in warnings[0]


def test_latest_missing_year_row_fails_closed() -> None:
    rows = [
        _list_row(
            disclosure_no=22820,
            disclosure_type="1",
            disclosure_name="2025년도 결산정기공시",
            reg_date="2026-03-01",
        ),
        _list_row(
            disclosure_no=26000,
            disclosure_type="2",
            disclosure_name="상반기결산공시",
            reg_date="2026-08-29",
        ),
    ]

    with pytest.raises(CuFundingContractError, match="최신권 공시"):
        _select_latest_disclosures_with_warnings(
            rows,
            cu_ingno="02002",
            periods=12,
        )


def test_historical_summary_mismatch_is_quarantined_but_latest_fails() -> None:
    disclosure = _disclosure(year=2022, disclosure_no=9786)
    mismatched_html = _summary_html(year=2021, prior=2020, amount="1,925")

    point, warning = _parse_summary_with_history_policy(
        mismatched_html,
        disclosure=disclosure,
        institution_id="inst-1",
        institution_name="테스트",
        source_locator="https://example.test/summary",
        is_latest=False,
    )
    assert point is None
    assert warning is not None
    assert "summary contract mismatch" in warning
    assert "9786" in warning

    with pytest.raises(CuFundingContractError, match="header 불일치"):
        _parse_summary_with_history_policy(
            mismatched_html,
            disclosure=disclosure,
            institution_id="inst-1",
            institution_name="테스트",
            source_locator="https://example.test/summary",
            is_latest=True,
        )


'''
if extra_tests not in tests:
    if anchor not in tests:
        raise SystemExit("test insertion anchor missing")
    tests = tests.replace(anchor, extra_tests + anchor, 1)
    changed = True

if not changed:
    print("CU historical quarantine patch already applied")
else:
    funding_path.write_text(funding, encoding="utf-8")
    test_path.write_text(tests, encoding="utf-8")
    print("CU historical quarantine patch applied")
