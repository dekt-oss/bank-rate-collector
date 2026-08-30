import json

from scripts.volume_gate import (
    SEPARATE_DATA_PRODUCT_SOURCE_IDS,
    compare,
    main,
    report,
)


def _run(source_id: str, parsed_count: int) -> dict:
    return {
        "source_id": source_id,
        "status": "success",
        "parsed_count": parsed_count,
    }


def test_rate_publication_ignores_only_known_funding_data_products():
    summary = {
        "runs": [
            _run("data_go_agri_coop_funding", 1_126),
            _run("data_go_agri_coop_funding", 11_273),
            _run("data_go_savings_bank_funding", 240),
            _run("data_go_savings_bank_funding", 1_840),
            _run("cu", 30_521),
            _run("cu", 30_400),
        ]
    }

    changes = compare(summary)

    assert {change.source_id for change in changes} == {"cu"}
    assert report(changes) == 0


def test_diagnostic_mode_still_detects_funding_collapse():
    summary = {
        "runs": [
            _run("data_go_agri_coop_funding", 1_126),
            _run("data_go_agri_coop_funding", 11_273),
        ]
    }

    changes = compare(summary, include_separate_data_products=True)

    assert len(changes) == 1
    assert changes[0].source_id == "data_go_agri_coop_funding"
    assert changes[0].collapsed is True
    assert report(changes) == 1


def test_unknown_future_source_remains_fail_closed():
    summary = {
        "runs": [
            _run("future_rate_source", 100),
            _run("future_rate_source", 1_000),
        ]
    }

    changes = compare(summary)

    assert len(changes) == 1
    assert changes[0].source_id == "future_rate_source"
    assert changes[0].collapsed is True
    assert report(changes) == 1


def test_exclusion_is_exact_not_prefix_wide():
    summary = {
        "runs": [
            _run("data_go_future_rate", 100),
            _run("data_go_future_rate", 1_000),
        ]
    }

    changes = compare(summary)

    assert changes[0].source_id == "data_go_future_rate"
    assert changes[0].collapsed is True


def test_known_separate_data_product_contract_is_narrow():
    assert {
        "data_go_savings_bank_funding",
        "data_go_credit_union_funding",
        "data_go_agri_coop_funding",
    } == SEPARATE_DATA_PRODUCT_SOURCE_IDS


def test_cli_diagnostic_switch_restores_all_source_check(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "runs": [
                    _run("data_go_savings_bank_funding", 240),
                    _run("data_go_savings_bank_funding", 1_840),
                ]
            }
        ),
        encoding="utf-8",
    )

    assert main(["--summary", str(summary_path)]) == 0
    assert (
        main(
            [
                "--summary",
                str(summary_path),
                "--include-separate-data-products",
            ]
        )
        == 1
    )


def test_accept_behavior_is_unchanged_for_rate_source(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "runs": [
                    _run("cu", 100),
                    _run("cu", 1_000),
                ]
            }
        ),
        encoding="utf-8",
    )

    assert main(["--summary", str(summary_path)]) == 1
    assert main(["--summary", str(summary_path), "--accept"]) == 0


def test_small_baseline_rule_is_unchanged():
    summary = {
        "runs": [
            _run("cu", 2),
            _run("cu", 3),
        ]
    }

    changes = compare(summary)

    assert len(changes) == 1
    assert changes[0].collapsed is False
    assert report(changes) == 0
