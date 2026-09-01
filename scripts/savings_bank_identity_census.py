"""Read-only production census for savings-bank funding identity gaps."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rate_monitor.domain.identifiers import make_org_key
from rate_monitor.domain.normalization import normalize_institution_name

SOURCE_ID = "data_go_savings_bank_funding"
SECTOR = "savings_bank"
ENTITY_TYPE = "institution"
FEATURE_BRANCH = "fix/savings-bank-funding-identity-13-20260901"


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _json_object(value: object) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_links(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT l.source_id,
               l.source_entity_key,
               l.entity_id,
               l.source_name,
               l.source_payload_json,
               l.match_method,
               l.confidence,
               i.sector AS institution_sector,
               i.canonical_name
        FROM source_entity_links l
        LEFT JOIN institutions i ON i.id = l.entity_id
        WHERE l.entity_type = ?
          AND l.valid_to IS NULL
        """,
        (ENTITY_TYPE,),
    ).fetchall()
    links: list[dict[str, Any]] = []
    for row in rows:
        payload = _json_object(row["source_payload_json"])
        links.append(
            {
                "source_id": str(row["source_id"]),
                "source_entity_key": str(row["source_entity_key"]),
                "entity_id": str(row["entity_id"]),
                "source_name": (
                    str(row["source_name"]) if row["source_name"] is not None else None
                ),
                "source_crno": str(payload.get("crno") or "").strip() or None,
                "canonical_name": (
                    str(row["canonical_name"]) if row["canonical_name"] is not None else None
                ),
                "institution_sector": (
                    str(row["institution_sector"])
                    if row["institution_sector"] is not None
                    else None
                ),
                "match_method": (
                    str(row["match_method"]) if row["match_method"] is not None else None
                ),
                "confidence": (float(row["confidence"]) if row["confidence"] is not None else None),
            }
        )
    return links


def _unique_entities(links: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(link["entity_id"]): link for link in links}


def _normalized_match(link: dict[str, Any], source_name: str) -> bool:
    canonical = str(link.get("canonical_name") or "")
    return bool(canonical) and (
        normalize_institution_name(canonical) == normalize_institution_name(source_name)
    )


def _public_link(link: dict[str, Any], source_name: str) -> dict[str, Any]:
    result = dict(link)
    result["canonical_name_exact_normalized_match"] = _normalized_match(
        link,
        source_name,
    )
    return result


def _classify(
    *,
    source_key: str,
    source_name: str,
    source_crno: str | None,
    own_links: list[dict[str, Any]],
    same_key_links: list[dict[str, Any]],
    crno_links: list[dict[str, Any]],
    name_links: list[dict[str, Any]],
) -> tuple[str, str, str | None]:
    own_entities = _unique_entities(own_links)
    if own_links:
        if len(own_entities) != 1:
            return (
                "blocked_ambiguous_same_source_link",
                "same-source active link가 둘 이상 canonical entity를 가리킨다",
                None,
            )
        own = next(iter(own_entities.values()))
        own_crno = str(own.get("source_crno") or "") or None
        if source_crno and own_crno and source_crno != own_crno:
            return (
                "blocked_same_source_crno_conflict",
                f"same-source link CRNO {own_crno} != source CRNO {source_crno}",
                None,
            )
        return (
            "stale_observation_link_present",
            "same-source exact link는 있으나 latest funding observation은 unmapped다",
            str(own["entity_id"]),
        )

    cross_source = [link for link in same_key_links if link["source_id"] != SOURCE_ID]
    exact_name = [
        link
        for link in cross_source
        if link["institution_sector"] == SECTOR and _normalized_match(link, source_name)
    ]
    exact_entities = _unique_entities(exact_name)
    if len(exact_entities) == 1:
        candidate = next(iter(exact_entities.values()))
        return (
            "candidate_exact_cross_source_code_and_name",
            "동일 org key와 normalized canonical name이 cross-source에서 유일하다",
            str(candidate["entity_id"]),
        )
    if len(exact_entities) > 1:
        return (
            "blocked_ambiguous_exact_cross_source_code",
            "동일 org key+name이 둘 이상 canonical entity에 연결된다",
            None,
        )
    if cross_source:
        return (
            "blocked_exact_code_name_mismatch",
            "동일 org key link는 있으나 canonical name 계약이 일치하지 않는다",
            None,
        )

    crno_sector = [link for link in crno_links if link["institution_sector"] == SECTOR]
    crno_entities = _unique_entities(crno_sector)
    if source_crno and len(crno_entities) == 1:
        candidate = next(iter(crno_entities.values()))
        return (
            "candidate_exact_crno_unique",
            "동일 CRNO가 savings_bank canonical entity 하나에만 연결된다",
            str(candidate["entity_id"]),
        )
    if source_crno and len(crno_entities) > 1:
        return (
            "blocked_ambiguous_crno",
            "동일 CRNO가 둘 이상 canonical entity에 연결된다",
            None,
        )

    name_sector = [link for link in name_links if link["institution_sector"] == SECTOR]
    if _unique_entities(name_sector):
        return (
            "unresolved_name_only_hint",
            "normalized name 후보만 있어 exact identifier 없이 자동 매핑할 수 없다",
            None,
        )
    return (
        "unresolved_no_exact_identifier",
        f"{source_key}: 동일 code/CRNO exact evidence가 active link에 없다",
        None,
    )


def _latest_observations(conn: sqlite3.Connection) -> tuple[str, list[sqlite3.Row]]:
    row = conn.execute(
        """
        SELECT MAX(source_effective_month)
        FROM institution_funding_observations
        WHERE source_id = ?
          AND sector = ?
          AND valid_to IS NULL
        """,
        (SOURCE_ID, SECTOR),
    ).fetchone()
    latest_month = str(row[0] or "")
    if not latest_month:
        raise RuntimeError("no active savings-bank funding observations")
    rows = conn.execute(
        """
        SELECT source_institution_key,
               source_institution_name,
               source_crno,
               institution_id,
               identity_status,
               source_effective_month
        FROM institution_funding_observations
        WHERE source_id = ?
          AND sector = ?
          AND source_effective_month = ?
          AND valid_to IS NULL
        ORDER BY source_institution_key
        """,
        (SOURCE_ID, SECTOR, latest_month),
    ).fetchall()
    if not rows:
        raise RuntimeError(f"no savings-bank rows for {latest_month}")
    return latest_month, rows


def build_census(db_path: Path) -> dict[str, Any]:
    with _open_readonly(db_path) as conn:
        required = {
            "institution_funding_observations",
            "source_entity_links",
            "institutions",
        }
        tables = {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = required - tables
        if missing:
            raise RuntimeError(f"required tables missing: {sorted(missing)}")
        latest_month, observations = _latest_observations(conn)
        links = _load_links(conn)

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_crno: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in links:
        by_key[str(link["source_entity_key"])].append(link)
        crno = str(link.get("source_crno") or "")
        if crno:
            by_crno[crno].append(link)
        for name in (link.get("canonical_name"), link.get("source_name")):
            normalized = normalize_institution_name(str(name or ""))
            if normalized:
                by_name[normalized].append(link)

    mapped_count = sum(row["institution_id"] is not None for row in observations)
    gaps = [row for row in observations if row["institution_id"] is None]
    counts: Counter[str] = Counter()
    output_rows: list[dict[str, Any]] = []
    for row in gaps:
        source_key = str(row["source_institution_key"])
        source_name = str(row["source_institution_name"])
        source_crno = str(row["source_crno"] or "").strip() or None
        org_key = make_org_key(
            sector=SECTOR,
            source_institution_key=source_key,
            institution_name=source_name,
        )
        same_key = by_key.get(org_key, [])
        own = [link for link in same_key if link["source_id"] == SOURCE_ID]
        crno_links = by_crno.get(source_crno, []) if source_crno else []
        name_links = by_name.get(normalize_institution_name(source_name), [])
        classification, reason, candidate_id = _classify(
            source_key=source_key,
            source_name=source_name,
            source_crno=source_crno,
            own_links=own,
            same_key_links=same_key,
            crno_links=crno_links,
            name_links=name_links,
        )
        counts[classification] += 1
        output_rows.append(
            {
                "source_fncoCd": source_key,
                "source_crno": source_crno,
                "source_name": source_name,
                "source_effective_month": str(row["source_effective_month"]),
                "observation_identity_status": str(row["identity_status"] or ""),
                "org_key": org_key,
                "classification": classification,
                "candidate_institution_id": candidate_id,
                "reason": reason,
                "same_key_links": [_public_link(link, source_name) for link in same_key],
                "crno_links": [_public_link(link, source_name) for link in crno_links],
                "name_only_links": [_public_link(link, source_name) for link in name_links],
            }
        )

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_id": SOURCE_ID,
        "sector": SECTOR,
        "latest_source_effective_month": latest_month,
        "source_population": len(observations),
        "observation_mapped_count": mapped_count,
        "observation_unmapped_count": len(gaps),
        "classification_counts": dict(sorted(counts.items())),
        "write_back_performed": False,
        "rows": output_rows,
    }


def run_feature_copycheck(db_path: Path) -> dict[str, Any]:
    """Run the feature branch validator on a second runner-local DB copy."""
    work_dir = db_path.parent
    copy_path = work_dir / "rate_monitor.savings-bank-identity-copy.sqlite3"
    out_json = work_dir / "savings-bank-identity-remediation-copycheck.json"
    out_md = work_dir / "savings-bank-identity-remediation-copycheck.md"
    shutil.copy2(db_path, copy_path)

    temp_root = Path(tempfile.mkdtemp(prefix="savings-bank-identity-feature-"))
    feature_repo = temp_root / "repo"
    remote_ref = f"refs/remotes/origin/{FEATURE_BRANCH}"
    try:
        subprocess.run(
            [
                "git",
                "fetch",
                "--force",
                "--depth=1",
                "origin",
                f"{FEATURE_BRANCH}:{remote_ref}",
            ],
            check=True,
        )
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(feature_repo), remote_ref],
            check=True,
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(feature_repo / "src")
        subprocess.run(
            [
                sys.executable,
                str(feature_repo / "scripts/validate_savings_bank_identity_reconciliation.py"),
                "--db",
                str(copy_path.resolve()),
                "--expected-population",
                "79",
                "--expected-before-mapped",
                "66",
                "--expected-new-mapped",
                "13",
                "--out-json",
                str(out_json.resolve()),
                "--out-md",
                str(out_md.resolve()),
            ],
            cwd=feature_repo,
            env=env,
            check=True,
        )
        return json.loads(out_json.read_text(encoding="utf-8"))
    finally:
        if feature_repo.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(feature_repo)],
                check=False,
            )
        shutil.rmtree(temp_root, ignore_errors=True)
        copy_path.unlink(missing_ok=True)
        Path(str(copy_path) + "-wal").unlink(missing_ok=True)
        Path(str(copy_path) + "-shm").unlink(missing_ok=True)


def render_markdown(census: dict[str, Any]) -> str:
    lines = [
        "# Savings Bank Identity Census — read-only production evidence",
        "",
        "```yaml",
        "document_type: runtime_evidence",
        "mode: read_only",
        f"latest_source_effective_month: {census['latest_source_effective_month']}",
        f"source_population: {census['source_population']}",
        f"observation_mapped_count: {census['observation_mapped_count']}",
        f"observation_unmapped_count: {census['observation_unmapped_count']}",
        "write_back_performed: false",
        "```",
        "",
        "## Classification summary",
        "",
    ]
    for key, value in census["classification_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Gap rows",
            "",
            "| fncoCd | source name | CRNO | classification | candidate | reason |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in census["rows"]:
        reason = str(row["reason"]).replace("|", "\\|")
        lines.append(
            "| {source_fncoCd} | {source_name} | {source_crno} | "
            "`{classification}` | {candidate} | {reason} |".format(
                source_fncoCd=row["source_fncoCd"],
                source_name=str(row["source_name"]).replace("|", "\\|"),
                source_crno=row["source_crno"] or "-",
                classification=row["classification"],
                candidate=row["candidate_institution_id"] or "-",
                reason=reason,
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation rule",
            "",
            "- exact-code/name and unique-CRNO results are remediation candidates,",
            "  not automatic writes.",
            "- `unresolved_name_only_hint` is insufficient for mapping.",
            "- any `blocked_*` result stays unresolved until its conflict is explained.",
            "- this diagnostic never updates links or funding observations.",
            "",
        ]
    )
    copycheck = census.get("remediation_copycheck")
    if isinstance(copycheck, dict):
        lines.extend(
            [
                "## Feature remediation on second runner-local copy",
                "",
                f"- branch: `{FEATURE_BRANCH}`",
                f"- before mapped: {copycheck['before_mapped']}/{copycheck['source_population']}",
                f"- after mapped: {copycheck['after_mapped']}/{copycheck['source_population']}",
                f"- newly mapped: {len(copycheck['newly_mapped'])}",
                f"- non-identity changes: {copycheck['non_identity_changes']}",
                "- existing mapped identity changes: "
                f"{copycheck['existing_mapped_identity_changes']}",
                f"- second reconciliation mapped: {copycheck['second_reconciliation']['mapped']}",
                f"- production write-back: {copycheck['production_write_back_performed']}",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    census = build_census(args.db)
    census["remediation_copycheck"] = run_feature_copycheck(args.db)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(census, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.out_md.write_text(render_markdown(census), encoding="utf-8")
    print(
        "savings identity census",
        f"month={census['latest_source_effective_month']}",
        f"population={census['source_population']}",
        f"mapped={census['observation_mapped_count']}",
        f"unmapped={census['observation_unmapped_count']}",
        f"classifications={census['classification_counts']}",
        f"copycheck_after={census['remediation_copycheck']['after_mapped']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
