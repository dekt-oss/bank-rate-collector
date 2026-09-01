"""Read-only census for savings-bank funding identity gaps.

This diagnostic never mutates the production database. It classifies the latest
Data.go savings-bank funding identities against existing canonical links and
reports exact-identifier evidence separately from name-only hints.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rate_monitor.domain.identifiers import make_org_key
from rate_monitor.domain.normalization import normalize_institution_name

SOURCE_ID = "data_go_savings_bank_funding"
SECTOR = "savings_bank"
ENTITY_TYPE = "institution"


@dataclass(frozen=True)
class LinkEvidence:
    source_id: str
    source_entity_key: str
    entity_id: str
    source_name: str | None
    source_crno: str | None
    canonical_name: str | None
    institution_sector: str | None
    match_method: str | None
    confidence: float | None

    def as_dict(self, *, source_name: str) -> dict[str, Any]:
        canonical = str(self.canonical_name or "")
        return {
            "source_id": self.source_id,
            "source_entity_key": self.source_entity_key,
            "entity_id": self.entity_id,
            "source_name": self.source_name,
            "source_crno": self.source_crno,
            "canonical_name": self.canonical_name,
            "institution_sector": self.institution_sector,
            "match_method": self.match_method,
            "confidence": self.confidence,
            "canonical_name_exact_normalized_match": bool(canonical)
            and normalize_institution_name(canonical)
            == normalize_institution_name(source_name),
        }


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _link_evidence(row: sqlite3.Row) -> LinkEvidence:
    payload = _payload(row["source_payload_json"])
    crno = str(payload.get("crno") or "").strip() or None
    confidence = row["confidence"]
    return LinkEvidence(
        source_id=str(row["source_id"]),
        source_entity_key=str(row["source_entity_key"]),
        entity_id=str(row["entity_id"]),
        source_name=str(row["source_name"]) if row["source_name"] is not None else None,
        source_crno=crno,
        canonical_name=(
            str(row["canonical_name"]) if row["canonical_name"] is not None else None
        ),
        institution_sector=(
            str(row["institution_sector"])
            if row["institution_sector"] is not None
            else None
        ),
        match_method=str(row["match_method"]) if row["match_method"] is not None else None,
        confidence=float(confidence) if confidence is not None else None,
    )


def _unique_entities(links: list[LinkEvidence]) -> dict[str, LinkEvidence]:
    return {link.entity_id: link for link in links}


def _classify_gap(
    *,
    source_key: str,
    source_name: str,
    source_crno: str | None,
    own_links: list[LinkEvidence],
    same_key_links: list[LinkEvidence],
    crno_links: list[LinkEvidence],
    name_links: list[LinkEvidence],
) -> tuple[str, str, str | None]:
    if own_links:
        own_entities = _unique_entities(own_links)
        if len(own_entities) != 1:
            return (
                "blocked_ambiguous_same_source_link",
                "same-source active link가 둘 이상 entity를 가리킨다",
                None,
            )
        own = next(iter(own_entities.values()))
        if source_crno and own.source_crno and source_crno != own.source_crno:
            return (
                "blocked_same_source_crno_conflict",
                f"same-source link CRNO {own.source_crno} != source CRNO {source_crno}",
                None,
            )
        return (
            "stale_observation_link_present",
            "active same-source exact link가 이미 있으나 latest funding observation은 unmapped다",
            own.entity_id,
        )

    cross_source = [link for link in same_key_links if link.source_id != SOURCE_ID]
    exact_name = [
        link
        for link in cross_source
        if link.institution_sector == SECTOR
        and link.canonical_name
        and normalize_institution_name(link.canonical_name)
        == normalize_institution_name(source_name)
    ]
    exact_name_entities = _unique_entities(exact_name)
    if len(exact_name_entities) == 1:
        candidate = next(iter(exact_name_entities.values()))
        return (
            "candidate_exact_cross_source_code_and_name",
            "다른 source에서 동일 org key와 동일 normalized canonical name이 유일하게 확인됨",
            candidate.entity_id,
        )
    if len(exact_name_entities) > 1:
        return (
            "blocked_ambiguous_exact_cross_source_code",
            "동일 org key+name이 둘 이상 canonical entity로 연결됨",
            None,
        )
    if cross_source:
        return (
            "blocked_exact_code_name_mismatch",
            "동일 org key의 cross-source link는 있으나 canonical name 계약이 일치하지 않음",
            None,
        )

    crno_sector_links = [link for link in crno_links if link.institution_sector == SECTOR]
    crno_entities = _unique_entities(crno_sector_links)
    if source_crno and len(crno_entities) == 1:
        candidate = next(iter(crno_entities.values()))
        return (
            "candidate_exact_crno_unique",
            "동일 CRNO가 savings_bank canonical entity 하나에만 연결됨",
            candidate.entity_id,
        )
    if source_crno and len(crno_entities) > 1:
        return (
            "blocked_ambiguous_crno",
            "동일 CRNO가 둘 이상 canonical entity에 연결됨",
            None,
        )

    name_entities = _unique_entities(
        [link for link in name_links if link.institution_sector == SECTOR]
    )
    if name_entities:
        return (
            "unresolved_name_only_hint",
            "normalized name 후보는 있으나 exact identifier evidence가 없어 자동 매핑 금지",
            None,
        )
    return (
        "unresolved_no_exact_identifier",
        f"{source_key}: active link에서 동일 code/CRNO exact evidence를 찾지 못함",
        None,
    )


def build_census(db_path: Path) -> dict[str, Any]:
    with _open_readonly(db_path) as conn:
        required = {
            "institution_funding_observations",
            "source_entity_links",
            "institutions",
        }
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = required - tables
        if missing:
            raise RuntimeError(f"required tables missing: {sorted(missing)}")

        latest_month_row = conn.execute(
            """
            SELECT MAX(source_effective_month)
            FROM institution_funding_observations
            WHERE source_id = ?
              AND sector = ?
              AND valid_to IS NULL
            """,
            (SOURCE_ID, SECTOR),
        ).fetchone()
        latest_month = str(latest_month_row[0] or "")
        if not latest_month:
            raise RuntimeError("no active savings-bank funding observations")

        observations = conn.execute(
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
        if not observations:
            raise RuntimeError(f"no savings-bank rows for latest month {latest_month}")

        link_rows = conn.execute(
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

    all_links = [_link_evidence(row) for row in link_rows]
    by_key: dict[str, list[LinkEvidence]] = defaultdict(list)
    by_crno: dict[str, list[LinkEvidence]] = defaultdict(list)
    by_normalized_name: dict[str, list[LinkEvidence]] = defaultdict(list)
    for link in all_links:
        by_key[link.source_entity_key].append(link)
        if link.source_crno:
            by_crno[link.source_crno].append(link)
        for name in (link.canonical_name, link.source_name):
            normalized = normalize_institution_name(str(name or ""))
            if normalized:
                by_normalized_name[normalized].append(link)

    mapped_count = sum(row["institution_id"] is not None for row in observations)
    gaps = [row for row in observations if row["institution_id"] is None]
    rows: list[dict[str, Any]] = []
    classifications: Counter[str] = Counter()
    for row in gaps:
        source_key = str(row["source_institution_key"])
        source_name = str(row["source_institution_name"])
        source_crno = str(row["source_crno"] or "").strip() or None
        org_key = make_org_key(
            sector=SECTOR,
            source_institution_key=source_key,
            institution_name=source_name,
        )
        same_key_links = by_key.get(org_key, [])
        own_links = [link for link in same_key_links if link.source_id == SOURCE_ID]
        crno_links = by_crno.get(source_crno, []) if source_crno else []
        name_links = by_normalized_name.get(normalize_institution_name(source_name), [])
        classification, reason, candidate_id = _classify_gap(
            source_key=source_key,
            source_name=source_name,
            source_crno=source_crno,
            own_links=own_links,
            same_key_links=same_key_links,
            crno_links=crno_links,
            name_links=name_links,
        )
        classifications[classification] += 1
        rows.append(
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
                "same_key_links": [
                    link.as_dict(source_name=source_name) for link in same_key_links
                ],
                "crno_links": [
                    link.as_dict(source_name=source_name) for link in crno_links
                ],
                "name_only_links": [
                    link.as_dict(source_name=source_name) for link in name_links
                ],
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
        "classification_counts": dict(sorted(classifications.items())),
        "write_back_performed": False,
        "rows": rows,
    }


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
            "| fncoCd | source name | CRNO | classification | candidate institution | reason |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in census["rows"]:
        reason = str(row["reason"]).replace("|", "\\|")
        lines.append(
            "| {source_fncoCd} | {source_name} | {source_crno} | `{classification}` | "
            "{candidate} | {reason} |".format(
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
            "- `candidate_exact_cross_source_code_and_name` and `candidate_exact_crno_unique` are",
            "  **remediation candidates**, not automatic writes.",
            "- `unresolved_name_only_hint` is explicitly insufficient for mapping.",
            "- any `blocked_*` classification must remain unresolved until the conflict is explained.",
            "- this diagnostic does not update `source_entity_links` or funding observations.",
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
