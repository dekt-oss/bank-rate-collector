from __future__ import annotations

import ast
from pathlib import Path

GUARDED_PATHS = (
    Path("scripts/source_discrepancy_official_capture.py"),
    Path("src/rate_monitor/services/official_evidence_policy.py"),
)

FORBIDDEN_IMPORT_PREFIXES = (
    "rate_monitor.collectors",
    "rate_monitor.db",
    "rate_monitor.services.collection_service",
    "rate_monitor.services.entity_service",
    "sqlalchemy",
)

FORBIDDEN_SYMBOLS = {
    "CollectionRun",
    "RateObservation",
    "RawArtifact",
    "Session",
    "session_scope",
    "persist_rows",
    "save_raw_artifacts",
}


def _imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _names(tree: ast.AST) -> set[str]:
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def test_official_evidence_modules_cannot_import_canonical_write_path() -> None:
    for path in GUARDED_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = _imports(tree)
        forbidden_imports = sorted(
            name
            for name in imports
            if any(name.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES)
        )
        assert not forbidden_imports, f"{path}: forbidden write-path imports {forbidden_imports}"

        forbidden_symbols = sorted(_names(tree) & FORBIDDEN_SYMBOLS)
        assert not forbidden_symbols, f"{path}: forbidden write symbols {forbidden_symbols}"
