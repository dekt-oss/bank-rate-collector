from pathlib import Path


def test_size_peer_bootstrap_doc_requires_cleanup_after_seed() -> None:
    doc = Path("docs/ops/20260907-size-peer-production-bootstrap.md").read_text(
        encoding="utf-8"
    )

    assert "collector/parser/identity/persistence 코드는 변경하지 않는다" in doc
    assert "202512" in doc
    assert "authoritative R2" in doc
    assert "bootstrap 성공 후 `push` trigger" in doc
    assert "최대 1회" in doc
