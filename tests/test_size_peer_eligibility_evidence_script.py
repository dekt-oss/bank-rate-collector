from scripts.size_peer_eligibility_evidence import _fsb_branch_capable_codes


def test_fsb_branch_evidence_requires_explicit_branch_member() -> None:
    codes, summary = _fsb_branch_capable_codes(
        [
            {"FINAN_COMP_CODE": "001", "JOIN_LOCATION": "1,2,3"},
            {"FINAN_COMP_CODE": "002", "JOIN_LOCATION": "2,3"},
            {"FINAN_COMP_CODE": "003", "JOIN_LOCATION": "1"},
            {"FINAN_COMP_CODE": "004", "JOIN_LOCATION": ""},
        ]
    )
    assert codes == {"001", "003"}
    assert summary["institution_count"] == 4
    assert summary["branch_capable_institution_count"] == 2
    assert summary["unknown_channel_rows"] == 1


def test_fsb_branch_evidence_rejects_missing_official_institution_code() -> None:
    try:
        _fsb_branch_capable_codes([{"JOIN_LOCATION": "1"}])
    except RuntimeError as exc:
        assert "FINAN_COMP_CODE" in str(exc)
    else:
        raise AssertionError("missing FSB official institution code must fail closed")
