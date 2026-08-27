from pathlib import Path

WRITER_GROUP_LINE = "  group: rate-data-writer\n"
WRITER_CONCURRENCY_BLOCK = (
    "concurrency:\n"
    "  group: rate-data-writer\n"
    "  queue: max\n"
    "  cancel-in-progress: false\n"
)
EXPECTED_WRITER_WORKFLOWS = {
    "collect.yml",
    "collect-institution-funding.yml",
    "collect-nh.yml",
    "collect-savings-fast.yml",
    "storage-check.yml",
}


def test_rate_data_writer_workflows_preserve_pending_queue() -> None:
    matched: set[str] = set()
    for path in Path(".github/workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        if WRITER_GROUP_LINE not in text:
            continue
        matched.add(path.name)
        assert WRITER_CONCURRENCY_BLOCK in text, path

    assert matched == EXPECTED_WRITER_WORKFLOWS
