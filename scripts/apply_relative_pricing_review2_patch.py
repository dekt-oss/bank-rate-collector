from pathlib import Path

SERVICE = Path('src/rate_monitor/services/relative_pricing_strategy_payload.py')
TESTS = Path('tests/test_relative_pricing_strategy_payload.py')


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    assert count == 1, f'{label}: expected exactly one match, got {count}'
    return text.replace(old, new, 1)


service = SERVICE.read_text()
service = replace_once(
    service,
    'from rate_monitor.services.pricing_peer_position import (\n',
    'from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate\n'
    'from rate_monitor.services.rate_funding_matrix_service import RATE_REPRESENTATIVE\n'
    'from rate_monitor.services.pricing_peer_position import (\n',
    label='service imports',
)
service = replace_once(
    service,
    'RELATIVE_PRICING_CONTRACT_VERSION = "2"',
    'RELATIVE_PRICING_CONTRACT_VERSION = "3"',
    label='contract version',
)
service = replace_once(
    service,
    '        "representative_rate_reconciliation": None,\n'
    '        "pricing_peer_position": None,',
    '        "representative_rate_reconciliation": None,\n'
    '        "representative_rate_reconciliations": {},\n'
    '        "pricing_peer_position": None,',
    label='unavailable reconciliation map',
)

start = service.index('def _representative_rate_reconciliation(')
end = service.index('\ndef _radar_rows(', start)
new_reconciliation = '''def _observation_date(value: date | datetime | str | None) -> str | None:\n    if value is None:\n        return None\n    if isinstance(value, datetime):\n        return value.date().isoformat()\n    if isinstance(value, date):\n        return value.isoformat()\n    text = str(value).strip()\n    if not text:\n        return None\n    try:\n        return date.fromisoformat(text[:10]).isoformat()\n    except ValueError:\n        return None\n\n\ndef _representative_rate_reconciliation(\n    *,\n    pricing_representative: InstitutionRepresentativeRate,\n    matrix_representative_rate_pct: Decimal | float | str | None,\n    matrix_representative_policy_id: str | None,\n    matrix_representative_rate_as_of: date | datetime | str | None,\n    difference_reason: str | None,\n) -> dict[str, Any]:\n    matrix_policy = str(matrix_representative_policy_id or "").strip()\n    pricing_date = _observation_date(pricing_representative.rate_as_of)\n    matrix_date = _observation_date(matrix_representative_rate_as_of)\n    base = {\n        "pricing_policy_id": pricing_representative.policy_id,\n        "pricing_policy_version": pricing_representative.policy_version,\n        "pricing_rate_pct": pricing_representative.rate_pct,\n        "pricing_rate_as_of": pricing_date,\n        "matrix_policy_id": matrix_policy or None,\n        "matrix_rate_pct": None,\n        "matrix_rate_as_of": matrix_date,\n        "gap_bp": None,\n        "difference_reason": None,\n    }\n    if matrix_representative_rate_pct is None or not matrix_policy:\n        return {"status": "unresolved", **base}\n    if matrix_policy != RATE_REPRESENTATIVE:\n        return {"status": "policy_mismatch", **base}\n    try:\n        matrix_rate = normalize_rate(matrix_representative_rate_pct)\n    except (ValueError, ArithmeticError):\n        return {"status": "invalid", **base}\n    base["matrix_rate_pct"] = matrix_rate\n    if pricing_date is None or matrix_date is None:\n        return {"status": "temporal_unresolved", **base}\n    if pricing_date != matrix_date:\n        return {"status": "temporal_mismatch", **base}\n\n    gap_bp = _peer_gap_bp(pricing_representative.rate_pct, matrix_rate)\n    normalized_reason = str(difference_reason or "").strip() or None\n    if gap_bp == 0:\n        status = "matched"\n        normalized_reason = None\n    elif normalized_reason:\n        status = "explained"\n    else:\n        status = "unexplained"\n    return {\n        "status": status,\n        **base,\n        "gap_bp": gap_bp,\n        "difference_reason": normalized_reason,\n    }\n\n'''
service = service[:start] + new_reconciliation + service[end + 1 :]

service = replace_once(
    service,
    '    market_position: Mapping[str, Any] | None = None,\n'
    '    matrix_representative_rate_pct: Decimal | float | str | None = None,',
    '    market_position: Mapping[str, Any] | None = None,\n'
    '    matrix_representatives: Mapping[str, Mapping[str, Any]] | None = None,\n'
    '    representative_rate_difference_reasons: Mapping[str, str] | None = None,\n'
    '    matrix_representative_rate_pct: Decimal | float | str | None = None,',
    label='signature matrix mapping',
)
service = replace_once(
    service,
    '    Core pricing peers always exclude special offers. ``include_special_offer``\n'
    '    only opts into a separately labeled radar population. A Matrix representative\n'
    '    must also be supplied; if it disagrees with the pricing representative, the\n'
    '    difference requires an explicit factual explanation before the payload can be\n'
    '    marked ready.\n',
    '    Special-offer core/radar behavior is not silently inferred. Until the\n'
    '    repository contract is explicitly promoted, ``include_special_offer=True``\n'
    '    fails closed. Matrix evidence must be supplied for every displayed canonical\n'
    '    institution, with the canonical Matrix policy and the same observation date.\n',
    label='docstring policy',
)
old_radar = '''    rate_rows = list(rate_candidates)\n    names = institution_names or {}\n    radar_representatives = _special_offer_representatives(\n        rate_rows,\n        sector=sector,\n        product_type=product_type,\n        term_months=term_months,\n        availability_match_key=availability_match_key,\n        join_channel=join_channel,\n        retreating_sources=retreating_sources,\n        enabled=include_special_offer,\n    )\n    radar = _radar_rows(radar_representatives, names=names)\n\n    # Core pricing ranking never includes a promotional product.\n'''
new_radar = '''    rate_rows = list(rate_candidates)\n    names = institution_names or {}\n    if include_special_offer:\n        raise ValueError(\n            "special-offer core/radar policy is not approved; "\n            "include_special_offer must remain False"\n        )\n    radar: list[dict[str, Any]] = []\n\n    # Core pricing ranking remains the existing non-promotional population.\n'''
service = replace_once(service, old_radar, new_radar, label='special offer fail closed')

old_block_start = service.index('    reconciliation = _representative_rate_reconciliation(')
old_block_end = service.index('    funding_by_id, funding_analysis_month = _funding_index', old_block_start)
new_block = '''    matrix_by_id: dict[str, Mapping[str, Any]] = dict(matrix_representatives or {})\n    if anchor_id not in matrix_by_id and (\n        matrix_representative_rate_pct is not None\n        or matrix_representative_policy_id is not None\n        or matrix_representative_rate_as_of is not None\n    ):\n        matrix_by_id[anchor_id] = {\n            "rate_pct": matrix_representative_rate_pct,\n            "policy_id": matrix_representative_policy_id,\n            "rate_as_of": matrix_representative_rate_as_of,\n        }\n    reasons = dict(representative_rate_difference_reasons or {})\n    if representative_rate_difference_reason and anchor_id not in reasons:\n        reasons[anchor_id] = representative_rate_difference_reason\n\n    reconciliations: dict[str, dict[str, Any]] = {}\n    for representative in representatives:\n        evidence = matrix_by_id.get(representative.institution_id, {})\n        if not isinstance(evidence, Mapping):\n            raise ValueError(\n                "matrix representative evidence must be a mapping for institution "\n                + representative.institution_id\n            )\n        reconciliations[representative.institution_id] = (\n            _representative_rate_reconciliation(\n                pricing_representative=representative,\n                matrix_representative_rate_pct=evidence.get("rate_pct"),\n                matrix_representative_policy_id=evidence.get("policy_id"),\n                matrix_representative_rate_as_of=evidence.get("rate_as_of"),\n                difference_reason=reasons.get(representative.institution_id),\n            )\n        )\n\n    blocked_statuses = {\n        item["status"] for item in reconciliations.values()\n        if item["status"] not in {"matched", "explained"}\n    }\n    reconciliation = reconciliations[anchor_id]\n    if blocked_statuses:\n        if "temporal_mismatch" in blocked_statuses:\n            reason = "matrix_representative_rate_temporal_mismatch"\n        elif "temporal_unresolved" in blocked_statuses:\n            reason = "matrix_representative_rate_temporal_unresolved"\n        elif "invalid" in blocked_statuses:\n            reason = "matrix_representative_rate_invalid"\n        elif "policy_mismatch" in blocked_statuses:\n            reason = "matrix_representative_policy_noncanonical"\n        elif "unresolved" in blocked_statuses:\n            reason = "matrix_representative_rate_unresolved"\n        else:\n            reason = "representative_rate_policy_mismatch_unexplained"\n        payload = build_relative_pricing_unavailable_payload(reason=reason, as_of=as_of)\n        payload["representative_rate_reconciliation"] = _json_value(reconciliation)\n        payload["representative_rate_reconciliations"] = _json_value(reconciliations)\n        payload["special_offer_radar"] = _json_value(radar)\n        return payload\n\n'''
service = service[:old_block_start] + new_block + service[old_block_end:]
service = replace_once(
    service,
    '            "special_offer_radar_included": bool(include_special_offer),',
    '            "special_offer_radar_included": False,',
    label='scope radar flag',
)
service = replace_once(
    service,
    '        "representative_rate_reconciliation": reconciliation,\n'
    '        "pricing_peer_position": {',
    '        "representative_rate_reconciliation": reconciliation,\n'
    '        "representative_rate_reconciliations": reconciliations,\n'
    '        "pricing_peer_position": {',
    label='ready reconciliation map',
)
SERVICE.write_text(service)


tests = TESTS.read_text()
tests = replace_once(
    tests,
    'from decimal import Decimal\n',
    'from datetime import date\nfrom decimal import Decimal\n',
    label='tests date import',
)
tests = replace_once(
    tests,
    '        rate_pct=Decimal(rate),\n    )',
    '        rate_pct=Decimal(rate),\n        rate_as_of=date(2026, 9, 1),\n    )',
    label='test candidate date',
)
helper_marker = '\n\ndef _build(**kwargs):\n'
helper = '''\n\ndef _matrix(**rates: str) -> dict[str, dict[str, str]]:\n    return {\n        institution_id: {\n            "rate_pct": rate,\n            "policy_id": "institution_product_representative_max",\n            "rate_as_of": "2026-09-01",\n        }\n        for institution_id, rate in rates.items()\n    }\n'''
assert helper_marker in tests
tests = tests.replace(helper_marker, helper + helper_marker, 1)
tests = replace_once(
    tests,
    '        matrix_representative_rate_pct="3.50",\n'
    '        matrix_representative_policy_id="institution_product_representative_max",\n'
    '        matrix_representative_rate_as_of="2026-09-01",',
    '        matrix_representatives=_matrix(our="3.50", high="3.60", low="3.40"),',
    label='_build matrix mapping',
)
tests = tests.replace('RELATIVE_PRICING_CONTRACT_VERSION == "2"', 'RELATIVE_PRICING_CONTRACT_VERSION == "3"')
tests = tests.replace('payload["policies"]["contract_version"] == "2"', 'payload["policies"]["contract_version"] == "3"')
tests = tests.replace('"pricing_rate_as_of": None,', '"pricing_rate_as_of": "2026-09-01",', 1)
tests = tests.replace('"matrix_rate_pct": "3.50",', '"matrix_rate_pct": "3.5000",', 1)

replacements = [
    (
        '        matrix_representative_rate_pct="3.50",\n'
        '        matrix_representative_policy_id="institution_product_representative_max",\n'
        '        retreating_sources=set(),\n    )\n\n    position = payload["pricing_peer_position"]\n    assert payload["status"] == "ready"',
        '        matrix_representatives=_matrix(our="3.50", high="3.60"),\n'
        '        retreating_sources=set(),\n    )\n\n    position = payload["pricing_peer_position"]\n    assert payload["status"] == "ready"',
        'higher-peer mapping',
    ),
    (
        '        matrix_representative_rate_pct="3.60",\n'
        '        matrix_representative_policy_id="institution_product_representative_max",\n'
        '        retreating_sources=set(),\n    )\n\n    position = payload["pricing_peer_position"]',
        '        matrix_representatives=_matrix(our="3.60", low="3.40"),\n'
        '        retreating_sources=set(),\n    )\n\n    position = payload["pricing_peer_position"]',
        'no-higher mapping',
    ),
    (
        '            matrix_representative_rate_pct="3.50",\n'
        '            matrix_representative_policy_id="institution_product_representative_max",\n'
        '            retreating_sources=set(),\n        )\n\n\ndef test_mixed_funding_vintages_fail_closed_before_aggregation()',
        '            matrix_representatives=_matrix(our="3.50", peer="3.60"),\n'
        '            retreating_sources=set(),\n        )\n\n\ndef test_mixed_funding_vintages_fail_closed_before_aggregation()',
        'duplicate-funding mapping',
    ),
    (
        '            matrix_representative_rate_pct="3.50",\n'
        '            matrix_representative_policy_id="institution_product_representative_max",\n'
        '            retreating_sources=set(),\n        )\n\n\ndef test_matrix_representative_is_required_for_ready_payload()',
        '            matrix_representatives=_matrix(our="3.50", peer="3.60"),\n'
        '            retreating_sources=set(),\n        )\n\n\ndef test_matrix_representative_is_required_for_ready_payload()',
        'mixed-vintage mapping',
    ),
    (
        '        matrix_representative_rate_pct="3.45",\n'
        '        matrix_representative_policy_id="institution_product_representative_max",\n'
        '        retreating_sources=set(),\n    )\n\n    assert payload["status"] == "insufficient_data"',
        '        matrix_representatives=_matrix(our="3.45", peer="3.60"),\n'
        '        retreating_sources=set(),\n    )\n\n    assert payload["status"] == "insufficient_data"',
        'unexplained mismatch mapping',
    ),
    (
        '        matrix_representative_rate_pct="3.45",\n'
        '        matrix_representative_policy_id="institution_product_representative_max",\n'
        '        representative_rate_difference_reason="pricing scope excludes unmatched channel",',
        '        matrix_representatives=_matrix(our="3.45", peer="3.60"),\n'
        '        representative_rate_difference_reason="pricing scope excludes unmatched channel",',
        'explained mismatch mapping',
    ),
]
for old, new, label in replacements:
    tests = replace_once(tests, old, new, label=label)

tests = tests.replace('assert reconciliation["matrix_rate_pct"] == "3.45"', 'assert reconciliation["matrix_rate_pct"] == "3.4500"')

special_start = tests.index('def test_special_offer_is_radar_only_and_never_replaces_core_peer()')
special_end = tests.index('\n\ndef test_unavailable_payload_keeps_policy_versions_visible()', special_start)
special_test = '''def test_unapproved_special_offer_policy_fails_closed() -> None:\n    with pytest.raises(ValueError, match="special-offer core/radar policy is not approved"):\n        build_relative_pricing_strategy_payload(\n            [\n                _rate("our", "p-our", "3.50"),\n                _rate("peer", "p-peer-core", "3.60"),\n                _rate("peer", "p-peer-special", "4.50", special_offer=True),\n            ],\n            anchor_institution_id="our",\n            sector="savings_bank",\n            product_type="term_deposit",\n            term_months=12,\n            availability_match_key="nationwide",\n            include_special_offer=True,\n            retreating_sources=set(),\n        )\n'''
tests = tests[:special_start] + special_test + tests[special_end:]

extra_tests = '''\n\ndef test_matrix_policy_must_be_canonical_for_every_displayed_institution() -> None:\n    matrix = _matrix(our="3.50", peer="3.60")\n    matrix["peer"]["policy_id"] = "typo-policy"\n    payload = build_relative_pricing_strategy_payload(\n        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],\n        anchor_institution_id="our",\n        sector="savings_bank",\n        product_type="term_deposit",\n        term_months=12,\n        availability_match_key="nationwide",\n        matrix_representatives=matrix,\n        retreating_sources=set(),\n    )\n    assert payload["status"] == "insufficient_data"\n    assert payload["reason"] == "matrix_representative_policy_noncanonical"\n    assert payload["representative_rate_reconciliations"]["peer"]["status"] == "policy_mismatch"\n\n\ndef test_matrix_dates_must_match_pricing_observation_dates() -> None:\n    matrix = _matrix(our="3.50", peer="3.60")\n    matrix["peer"]["rate_as_of"] = "2026-08-31"\n    payload = build_relative_pricing_strategy_payload(\n        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],\n        anchor_institution_id="our",\n        sector="savings_bank",\n        product_type="term_deposit",\n        term_months=12,\n        availability_match_key="nationwide",\n        matrix_representatives=matrix,\n        retreating_sources=set(),\n    )\n    assert payload["status"] == "insufficient_data"\n    assert payload["reason"] == "matrix_representative_rate_temporal_mismatch"\n\n\ndef test_missing_peer_matrix_evidence_fails_closed() -> None:\n    payload = build_relative_pricing_strategy_payload(\n        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],\n        anchor_institution_id="our",\n        sector="savings_bank",\n        product_type="term_deposit",\n        term_months=12,\n        availability_match_key="nationwide",\n        matrix_representatives=_matrix(our="3.50"),\n        retreating_sources=set(),\n    )\n    assert payload["status"] == "insufficient_data"\n    assert payload["reason"] == "matrix_representative_rate_unresolved"\n    assert payload["representative_rate_reconciliations"]["peer"]["status"] == "unresolved"\n\n\ndef test_invalid_matrix_rate_fails_closed_before_gap_calculation() -> None:\n    matrix = _matrix(our="3.50", peer="3.60")\n    matrix["peer"]["rate_pct"] = "-1"\n    payload = build_relative_pricing_strategy_payload(\n        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],\n        anchor_institution_id="our",\n        sector="savings_bank",\n        product_type="term_deposit",\n        term_months=12,\n        availability_match_key="nationwide",\n        matrix_representatives=matrix,\n        retreating_sources=set(),\n    )\n    assert payload["status"] == "insufficient_data"\n    assert payload["reason"] == "matrix_representative_rate_invalid"\n'''
insert_at = tests.index('\n\ndef test_unavailable_payload_keeps_policy_versions_visible()')
tests = tests[:insert_at] + extra_tests + tests[insert_at:]
tests = tests.replace(
    '    assert payload["representative_rate_reconciliation"] is None\n',
    '    assert payload["representative_rate_reconciliation"] is None\n'
    '    assert payload["representative_rate_reconciliations"] == {}\n',
    1,
)
TESTS.write_text(tests)

print('patched service and tests')
