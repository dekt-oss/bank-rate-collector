from pathlib import Path

import yaml


WRITER_GROUP = "rate-data-writer"
EXPECTED_WRITER_WORKFLOWS = {
    "collect.yml",
    "collect-nh.yml",
    "collect-savings-fast.yml",
    "storage-check.yml",
}


def test_rate_data_writer_workflows_preserve_pending_queue() -> None:
    matched: set[str] = set()
    for path in Path(".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        concurrency = workflow.get("concurrency")
        if not isinstance(concurrency, dict) or concurrency.get("group") != WRITER_GROUP:
            continue
        matched.add(path.name)
        assert concurrency.get("queue") == "max", path
        assert concurrency.get("cancel-in-progress") is False, path

    assert matched == EXPECTED_WRITER_WORKFLOWS
