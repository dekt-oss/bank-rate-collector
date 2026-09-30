from pathlib import Path


WORKFLOW = Path(".github/workflows/publish-ui.yml")


def test_special_offer_radar_changes_trigger_publish_ui() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required_paths = (
        'src/rate_monitor/services/special_offer_*.py',
        'src/rate_monitor/db/special_offer_models.py',
        'src/rate_monitor/db/migrations/versions/*special_offer*.py',
    )

    for path in required_paths:
        assert f'- "{path}"' in text
