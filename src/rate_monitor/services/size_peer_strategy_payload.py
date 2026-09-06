"""Production-backed Strategy payload for Size Peer v1.

This module is intentionally read-only. It composes the already locked Size Peer
contracts from persisted canonical facts and never writes collector, identity or
financial state.

Two clocks remain separate:

* ``financial_as_of`` is the latest exact month where both supported sectors have
  both financial axes in the canonical funding table.
* ``eligibility_as_of`` is current selected-product evidence from rate observations.

Missing axes, unsupported identity, ambiguous identity and unsupported channel
summaries fail closed. In particular, ``any``/``unknown`` are never promoted to
REMOTE evidence.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from rate_monitor.services.institution_funding_read_model_db import (
    VERIFIED_IDENTITY_STATUSES,
)
from rate_monitor.services.size_peer_current_eligibility import (
    ELIGIBILITY_OVERLAY_POLICY_ID,
    ELIGIBILITY_OVERLAY_POLICY_VERSION,
    EligibilityEvidenceFact,
    SizePeerEligibilityEvidenceError,
    TwoAxisFinancialCandidate,
    apply_current_eligibility,
)
from rate_monitor.services.size_peer_similarity import (
    SIZE_PEER_RANKING_POLICY_ID,
    SIZE_PEER_RANKING_POLICY_VERSION,
    SizePeerRanking,
    nearest_for_display,
    rank_size_peers,
)
from rate_monitor.services.size_peer_universe import (
    BRANCH_BUSAN,
    BUSAN_ALL_DISTRICTS,
    REMOTE,
    SIZE_PEER_UNIVERSE_POLICY_ID,
    SIZE_PEER_UNIVERSE_POLICY_VERSION,
)
from rate_monitor.services.strategy_service_base import OUR_INSTITUTION_NAME

TERM_MONTHS = 12
DISPLAY_LIMIT = 8
FUNDING_METRIC = "deposit_liabilities_total"
ASSETS_METRIC = "total_assets"
NORMALIZED_UNIT = "million_krw"

SUPPORTED_SECTORS = ("savings_bank", "nh_local")
UNSUPPORTED_SECTORS = ("cu", "kfcc")
FINANCIAL_SOURCE_BY_SECTOR = {
    "savings_bank": "data_go_savings_bank_funding",
    "nh_local": "data_go_agri_coop_funding",
}
RATE_SOURCE_BY_SECTOR = {
    "savings_bank": "fsb",
    "nh_local": "nh_local",
}
_REMOTE_CHANNELS = frozenset({"internet", "mobile", "smartphone", "smart_phone"})

_REQUIRED_TABLES = frozenset(
    {
        "institutions",
        "institution_funding_observations",
        "products",
        "product_variants",
        "rate_observations",
        "collection_runs",
        "outlets",
        "source_entity_links",
    }
)


def _base_payload(*, reason: str | None = None) -> dict[str, Any]:
    return {
        "status": "unavailable" if reason else "ready",
        "reason": reason,
        "policy_id": SIZE_PEER_RANKING_POLICY_ID,
        "policy_version": SIZE_PEER_RANKING_POLICY_VERSION,
        "eligibility_policy_id": ELIGIBILITY_OVERLAY_POLICY_ID,
        "eligibility_policy_version": ELIGIBILITY_OVERLAY_POLICY_VERSION,
        "universe_policy_id": SIZE_PEER_UNIVERSE_POLICY_ID,
        "universe_policy_version": SIZE_PEER_UNIVERSE_POLICY_VERSION,
        "term_months": TERM_MONTHS,
        "supported_sectors": list(SUPPORTED_SECTORS),
        "unsupported_sectors": list(UNSUPPORTED_SECTORS),
        "coverage_note": "현재 총자산 비교 가능 업권: 저축은행 · 농·축협",
        "financial_as_of": None,
        "eligibility_as_of": None,
        "eligibility_source_as_of": {},
        "anchor": None,
        "financial_candidate_count": 0,
        "modes": {
            REMOTE: _mode_unavailable(REMOTE, reason or "not_built"),
            BRANCH_BUSAN: _mode_unavailable(BRANCH_BUSAN, reason or "not_built"),
        },
    }


def _mode_unavailable(mode: str, reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "eligibility_mode": mode,
        "financial_as_of": None,
        "eligibility_as_of": None,
        "eligible_count": 0,
        "ranked_count": 0,
        "display_count": 0,
        "display_rows": [],
    }


def _connect_read_only(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _positive_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed <= 0:
        return None
    return parsed


def _anchor_id(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        """
        SELECT id
        FROM institutions
        WHERE active = 1
          AND sector = 'savings_bank'
          AND canonical_name = ?
        ORDER BY id
        """,
        (OUR_INSTITUTION_NAME,),
    ).fetchall()
    if not rows:
        raise SizePeerEligibilityEvidenceError("anchor_missing")
    if len(rows) != 1:
        raise SizePeerEligibilityEvidenceError("identity_conflict")
    return str(rows[0]["id"])


def _financial_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    statuses = sorted(VERIFIED_IDENTITY_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    source_clauses = " OR ".join(
        "(ifo.sector = ? AND ifo.source_id = ?)" for _ in SUPPORTED_SECTORS
    )
    params: list[object] = [*statuses]
    for sector in SUPPORTED_SECTORS:
        params.extend((sector, FINANCIAL_SOURCE_BY_SECTOR[sector]))
    return conn.execute(
        f"""
        SELECT ifo.institution_id,
               i.canonical_name,
               ifo.sector,
               ifo.source_id,
               ifo.source_institution_key,
               ifo.source_crno,
               ifo.metric_code,
               ifo.source_effective_month,
               ifo.value,
               ifo.unit
        FROM institution_funding_observations AS ifo
        JOIN institutions AS i ON i.id = ifo.institution_id
        WHERE ifo.valid_to IS NULL
          AND ifo.institution_id IS NOT NULL
          AND i.active = 1
          AND ifo.identity_status IN ({placeholders})
          AND ifo.metric_code IN (?, ?)
          AND ifo.unit = ?
          AND ({source_clauses})
        ORDER BY ifo.source_effective_month, ifo.sector, ifo.institution_id, ifo.metric_code
        """,
        (
            *params[: len(statuses)],
            FUNDING_METRIC,
            ASSETS_METRIC,
            NORMALIZED_UNIT,
            *params[len(statuses) :],
        ),
    ).fetchall()


def _latest_exact_common_month(rows: list[sqlite3.Row]) -> str:
    by_sector: dict[str, dict[str, set[str]]] = {
        sector: defaultdict(set) for sector in SUPPORTED_SECTORS
    }
    for row in rows:
        value = _positive_decimal(row["value"])
        if value is None:
            continue
        sector = str(row["sector"])
        month = str(row["source_effective_month"] or "").strip()
        metric = str(row["metric_code"])
        if sector in by_sector and len(month) == 7:
            by_sector[sector][month].add(metric)

    common: set[str] | None = None
    required = {FUNDING_METRIC, ASSETS_METRIC}
    for sector in SUPPORTED_SECTORS:
        complete_months = {
            month for month, metrics in by_sector[sector].items() if required.issubset(metrics)
        }
        common = complete_months if common is None else common & complete_months
    if not common:
        raise SizePeerEligibilityEvidenceError("common_financial_month_missing")
    return max(common)


def _financial_candidates(
    rows: list[sqlite3.Row], *, month: str
) -> tuple[TwoAxisFinancialCandidate, ...]:
    grouped: dict[str, dict[str, sqlite3.Row]] = defaultdict(dict)
    identity_keys: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    names: dict[str, tuple[str, str]] = {}

    for row in rows:
        if str(row["source_effective_month"]) != month:
            continue
        value = _positive_decimal(row["value"])
        if value is None:
            continue
        institution_id = str(row["institution_id"])
        metric = str(row["metric_code"])
        if metric in grouped[institution_id]:
            raise SizePeerEligibilityEvidenceError("identity_conflict")
        grouped[institution_id][metric] = row
        identity_keys[institution_id].add(
            (
                str(row["source_id"]),
                str(row["source_institution_key"]),
                str(row["source_crno"] or ""),
            )
        )
        names[institution_id] = (str(row["canonical_name"]), str(row["sector"]))

    result: list[TwoAxisFinancialCandidate] = []
    for institution_id in sorted(grouped):
        pair = grouped[institution_id]
        if FUNDING_METRIC not in pair or ASSETS_METRIC not in pair:
            continue
        funding = pair[FUNDING_METRIC]
        assets = pair[ASSETS_METRIC]
        funding_key = (str(funding["source_id"]), str(funding["source_institution_key"]))
        assets_key = (str(assets["source_id"]), str(assets["source_institution_key"]))
        if funding_key != assets_key:
            raise SizePeerEligibilityEvidenceError("identity_conflict")
        funding_crno = str(funding["source_crno"] or "")
        assets_crno = str(assets["source_crno"] or "")
        if funding_crno and assets_crno and funding_crno != assets_crno:
            raise SizePeerEligibilityEvidenceError("identity_conflict")
        if len(identity_keys[institution_id]) > 2:
            raise SizePeerEligibilityEvidenceError("identity_conflict")
        funding_value = _positive_decimal(funding["value"])
        assets_value = _positive_decimal(assets["value"])
        if funding_value is None or assets_value is None:
            continue
        canonical_name, sector = names[institution_id]
        result.append(
            TwoAxisFinancialCandidate(
                institution_id=institution_id,
                canonical_name=canonical_name,
                sector=sector,
                source_institution_key=str(funding["source_institution_key"]),
                deposit_liabilities_total=funding_value,
                total_assets=assets_value,
            )
        )
    return tuple(result)


def _current_product_evidence(
    conn: sqlite3.Connection,
    *,
    candidate_ids: set[str],
) -> tuple[set[str], tuple[EligibilityEvidenceFact, ...], str, dict[str, str]]:
    if not candidate_ids:
        raise SizePeerEligibilityEvidenceError("financial_candidates_missing")
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = conn.execute(
        f"""
        SELECT i.id AS institution_id,
               i.sector,
               pv.join_channel,
               o.region_sido AS outlet_sido,
               o.region_sigungu AS outlet_sigungu,
               o.address AS outlet_address,
               cr.source_id,
               ro.last_seen_at
        FROM rate_observations AS ro
        JOIN product_variants AS pv ON pv.id = ro.variant_id
        JOIN products AS p ON p.id = pv.product_id
        JOIN institutions AS i ON i.id = p.institution_id
        JOIN collection_runs AS cr ON cr.id = ro.last_run_id
        LEFT JOIN outlets AS o ON o.id = pv.outlet_id AND o.active = 1
        WHERE ro.valid_to IS NULL
          AND COALESCE(ro.validation_status, 'valid') != 'error'
          AND p.active = 1
          AND i.active = 1
          AND p.product_type = 'term_deposit'
          AND pv.term_months = ?
          AND i.id IN ({placeholders})
          AND (
                (i.sector = 'savings_bank' AND cr.source_id = 'fsb')
             OR (i.sector = 'nh_local' AND cr.source_id = 'nh_local')
          )
        ORDER BY i.id, ro.last_seen_at DESC
        """,
        (TERM_MONTHS, *sorted(candidate_ids)),
    ).fetchall()
    if not rows:
        raise SizePeerEligibilityEvidenceError("current_product_evidence_missing")

    current_ids: set[str] = set()
    channels: dict[str, set[str]] = defaultdict(set)
    districts: dict[str, set[str]] = defaultdict(set)
    sectors: dict[str, str] = {}
    source_dates: dict[str, str] = {}

    for row in rows:
        institution_id = str(row["institution_id"])
        sector = str(row["sector"])
        source_id = str(row["source_id"])
        current_ids.add(institution_id)
        sectors[institution_id] = sector
        last_seen = str(row["last_seen_at"] or "")[:10]
        if len(last_seen) == 10:
            source_dates[source_id] = max(source_dates.get(source_id, ""), last_seen)

        if sector == "nh_local":
            channel = str(row["join_channel"] or "").strip().lower()
            if channel in _REMOTE_CHANNELS:
                channels[institution_id].add(channel)
            sido = str(row["outlet_sido"] or "").strip()
            sigungu = str(row["outlet_sigungu"] or "").strip()
            address = str(row["outlet_address"] or "").strip()
            if sido in {"부산", "부산광역시"} and sigungu in BUSAN_ALL_DISTRICTS and address:
                districts[institution_id].add(sigungu)

    # Savings-bank rate rows are head-office reference rows. Branch eligibility is
    # proven separately by the active official FSB outlet registry; join_channel
    # ANY is deliberately ignored rather than promoted to branch/remote evidence.
    savings_ids = sorted(
        institution_id
        for institution_id in current_ids
        if sectors.get(institution_id) == "savings_bank"
    )
    if savings_ids:
        savings_placeholders = ",".join("?" for _ in savings_ids)
        outlet_rows = conn.execute(
            f"""
            SELECT o.institution_id, o.region_sido, o.region_sigungu, o.address
            FROM outlets AS o
            JOIN source_entity_links AS sel
              ON sel.entity_type = 'outlet'
             AND sel.entity_id = o.id
             AND sel.source_id = 'fsb'
             AND sel.valid_to IS NULL
            WHERE o.active = 1
              AND o.institution_id IN ({savings_placeholders})
            ORDER BY o.institution_id, o.region_sigungu, o.id
            """,
            tuple(savings_ids),
        ).fetchall()
        for row in outlet_rows:
            institution_id = str(row["institution_id"])
            sido = str(row["region_sido"] or "").strip()
            sigungu = str(row["region_sigungu"] or "").strip()
            address = str(row["address"] or "").strip()
            if sido in {"부산", "부산광역시"} and sigungu in BUSAN_ALL_DISTRICTS and address:
                districts[institution_id].add(sigungu)

    facts = tuple(
        EligibilityEvidenceFact(
            institution_id=institution_id,
            source_channels=tuple(sorted(channels[institution_id])),
            busan_districts=tuple(sorted(districts[institution_id])),
            channel_evidence_source_id=(
                RATE_SOURCE_BY_SECTOR[sectors[institution_id]]
                if channels[institution_id]
                else None
            ),
            locality_evidence_source_id=(
                RATE_SOURCE_BY_SECTOR[sectors[institution_id]]
                if districts[institution_id]
                else None
            ),
        )
        for institution_id in sorted(current_ids)
    )
    eligibility_dates = sorted(source_dates.values())
    if not eligibility_dates:
        raise SizePeerEligibilityEvidenceError("eligibility_as_of_missing")
    # Conservative two-source clock: the surface claims only the date through which
    # all currently represented source families have been observed.
    eligibility_as_of = min(eligibility_dates)
    return current_ids, facts, eligibility_as_of, dict(sorted(source_dates.items()))


def _gap_ratio_pct(gap: Decimal) -> float:
    # The authoritative ranking stays in log space. This is presentation-only:
    # exp(|ln ratio|)-1 gives the symmetric multiplicative distance as a percent.
    return round(math.expm1(float(gap)) * 100.0, 1)


def _row_payload(row: Any, *, financial_as_of: str) -> dict[str, Any]:
    return {
        "rank": row.rank,
        "institution_id": row.institution_id,
        "institution": row.canonical_name,
        "sector": row.sector,
        "deposit_liabilities_total": format(row.deposit_liabilities_total, "f"),
        "total_assets": format(row.total_assets, "f"),
        "funding_gap": format(row.funding_gap, "f"),
        "assets_gap": format(row.assets_gap, "f"),
        "worst_axis_gap": format(row.worst_axis_gap, "f"),
        "funding_gap_ratio_pct": _gap_ratio_pct(row.funding_gap),
        "assets_gap_ratio_pct": _gap_ratio_pct(row.assets_gap),
        "worst_axis_gap_ratio_pct": _gap_ratio_pct(row.worst_axis_gap),
        "financial_as_of": financial_as_of,
    }


def _mode_payload(ranking: SizePeerRanking) -> dict[str, Any]:
    rows = nearest_for_display(ranking, limit=DISPLAY_LIMIT)
    if not ranking.rows:
        return {
            **_mode_unavailable(ranking.eligibility_mode, "no_ranked_peers"),
            "financial_as_of": ranking.financial_as_of,
            "eligibility_as_of": ranking.eligibility_as_of,
            "eligible_count": ranking.eligible_count_including_anchor,
        }
    return {
        "status": "ready",
        "reason": None,
        "eligibility_mode": ranking.eligibility_mode,
        "financial_as_of": ranking.financial_as_of,
        "eligibility_as_of": ranking.eligibility_as_of,
        "eligible_count": ranking.eligible_count_including_anchor,
        "ranked_count": ranking.ranked_count_excluding_anchor,
        "display_count": len(rows),
        "display_rows": [
            _row_payload(row, financial_as_of=ranking.financial_as_of) for row in rows
        ],
    }


def build_size_peer_strategy_payload(db_path: Path) -> dict[str, Any]:
    """Build the fail-closed Size Peer read model from persisted production facts."""
    if not db_path.exists():
        return _base_payload(reason="database_missing")

    conn = _connect_read_only(db_path)
    try:
        missing = sorted(_REQUIRED_TABLES - _tables(conn))
        if missing:
            return _base_payload(reason="required_table_missing:" + ",".join(missing))

        try:
            anchor_id = _anchor_id(conn)
            financial_rows = _financial_rows(conn)
            financial_as_of = _latest_exact_common_month(financial_rows)
            candidates = _financial_candidates(financial_rows, month=financial_as_of)
            by_id = {candidate.institution_id: candidate for candidate in candidates}
            anchor = by_id.get(anchor_id)
            if anchor is None:
                raise SizePeerEligibilityEvidenceError("anchor_financial_pair_missing")

            current_ids, facts, eligibility_as_of, source_dates = _current_product_evidence(
                conn,
                candidate_ids=set(by_id),
            )
            current_candidates = tuple(
                candidate for candidate in candidates if candidate.institution_id in current_ids
            )
            overlay = apply_current_eligibility(
                current_candidates,
                facts,
                financial_as_of=financial_as_of,
                eligibility_as_of=eligibility_as_of,
                term_months=TERM_MONTHS,
            )

            mode_payloads: dict[str, dict[str, Any]] = {}
            selections = {REMOTE: overlay.remote, BRANCH_BUSAN: overlay.branch_busan}
            for mode, selection in selections.items():
                eligible_ids = tuple(selection.eligible_ids)
                if anchor_id not in eligible_ids:
                    mode_payloads[mode] = {
                        **_mode_unavailable(mode, "anchor_not_eligible"),
                        "financial_as_of": financial_as_of,
                        "eligibility_as_of": eligibility_as_of,
                        "eligible_count": len(eligible_ids),
                    }
                    continue
                ranking = rank_size_peers(
                    current_candidates,
                    eligible_ids=eligible_ids,
                    anchor_id=anchor_id,
                    financial_as_of=financial_as_of,
                    eligibility_as_of=eligibility_as_of,
                    eligibility_mode=mode,
                )
                mode_payloads[mode] = _mode_payload(ranking)

            ready_modes = [
                mode for mode, payload in mode_payloads.items() if payload["status"] == "ready"
            ]
            payload = _base_payload(reason=None)
            payload.update(
                {
                    "status": "ready" if ready_modes else "unavailable",
                    "reason": None if ready_modes else "no_ready_mode",
                    "financial_as_of": financial_as_of,
                    "eligibility_as_of": eligibility_as_of,
                    "eligibility_source_as_of": source_dates,
                    "financial_candidate_count": len(candidates),
                    "current_product_candidate_count": len(current_candidates),
                    "anchor": {
                        "institution_id": anchor.institution_id,
                        "institution": anchor.canonical_name,
                        "sector": anchor.sector,
                        "deposit_liabilities_total": format(
                            anchor.deposit_liabilities_total, "f"
                        ),
                        "total_assets": format(anchor.total_assets, "f"),
                    },
                    "modes": mode_payloads,
                }
            )
            return payload
        except SizePeerEligibilityEvidenceError as exc:
            return _base_payload(reason=str(exc))
    except sqlite3.DatabaseError:
        return _base_payload(reason="database_not_production_ready")
    finally:
        conn.close()
