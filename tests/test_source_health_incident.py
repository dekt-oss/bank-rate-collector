from scripts.source_health_incident import classify_run


def _run(**overrides):
    row = {
        "status": "success",
        "raw_count": 10,
        "parsed_count": 100,
        "valid_count": 100,
        "message": "ok",
    }
    row.update(overrides)
    return row


def test_failed_volume_gate_is_incident_with_specific_code() -> None:
    state = classify_run(
        _run(
            status="failed",
            parsed_count=0,
            valid_count=0,
            message="SOURCE_EMPTY_RESULT: cu 전국 파싱 건수 0건",
        )
    )
    assert state.incident
    assert state.code == "SOURCE_EMPTY_RESULT"


def test_truncated_volume_gate_is_incident_with_specific_code() -> None:
    state = classify_run(
        _run(
            status="failed",
            parsed_count=999,
            valid_count=0,
            message="SOURCE_VOLUME_BELOW_MINIMUM: nh_local 999 < 1000",
        )
    )
    assert state.incident
    assert state.code == "SOURCE_VOLUME_BELOW_MINIMUM"


def test_legacy_success_with_raw_but_zero_parse_is_still_incident() -> None:
    state = classify_run(_run(status="success", raw_count=136, parsed_count=0, valid_count=0))
    assert state.incident
    assert state.code == "ZERO_PARSE_WHEN_RAW_EXISTS"


def test_healthy_success_does_not_open_incident() -> None:
    state = classify_run(_run())
    assert not state.incident
    assert state.code == "HEALTHY"


def test_missing_run_is_incident() -> None:
    state = classify_run(None)
    assert state.incident
    assert state.code == "NO_COLLECTION_RUN"
