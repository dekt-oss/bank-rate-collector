"""One-shot branch patcher for the savings-bank identity remediation.

This exists only because the connected GitHub contents API replaces whole files.
The script applies narrow, assertion-guarded edits and is removed after use.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    replace_once(
        "src/rate_monitor/collectors/data_go_funding/collector.py",
        "from rate_monitor.collectors.data_go_funding.aggregate_policy import (\n"
        "    AggregateValidationError,\n"
        "    partition_validated_agri_coop_rows,\n"
        ")\n",
        "from rate_monitor.collectors.data_go_funding.aggregate_policy import (\n"
        "    AggregateValidationError,\n"
        "    partition_validated_agri_coop_rows,\n"
        ")\n"
        "from rate_monitor.collectors.data_go_funding.savings_bank_identity import (\n"
        "    MAPPED_DUAL_SOURCE_STATUS,\n"
        "    resolve_savings_bank_dual_source_consensus,\n"
        ")\n",
    )
    replace_once(
        "src/rate_monitor/collectors/data_go_funding/collector.py",
        "    unique = {institution.id: institution for institution in candidates}\n"
        "    if len(unique) != 1:\n"
        "        return None, \"unmapped_no_exact_cross_source_code\"\n\n"
        "    institution = next(iter(unique.values()))\n",
        "    unique = {institution.id: institution for institution in candidates}\n"
        "    if len(unique) == 0 and point.sector == \"savings_bank\":\n"
        "        consensus = resolve_savings_bank_dual_source_consensus(\n"
        "            session,\n"
        "            source_institution_key=point.source_institution_key,\n"
        "            source_institution_name=point.source_institution_name,\n"
        "            source_crno=point.source_crno,\n"
        "        )\n"
        "        if consensus.institution_id is not None:\n"
        "            return consensus.institution_id, MAPPED_DUAL_SOURCE_STATUS\n"
        "    if len(unique) != 1:\n"
        "        return None, \"unmapped_no_exact_cross_source_code\"\n\n"
        "    institution = next(iter(unique.values()))\n",
    )

    replace_once(
        "src/rate_monitor/collectors/data_go_funding/operations.py",
        "from rate_monitor.collectors.data_go_funding.identity_reconciliation import (\n"
        "    reconcile_agri_funding_identity,\n"
        ")\n",
        "from rate_monitor.collectors.data_go_funding.identity_reconciliation import (\n"
        "    reconcile_agri_funding_identity,\n"
        ")\n"
        "from rate_monitor.collectors.data_go_funding.savings_bank_identity_reconciliation import (\n"
        "    reconcile_latest_savings_bank_funding_identity,\n"
        ")\n",
    )
    replace_once(
        "src/rate_monitor/collectors/data_go_funding/operations.py",
        "        if contract.sector == \"nh_local\" and result.status == \"success\":\n"
        "            identity = reconcile_agri_funding_identity(db_path)\n",
        "        if contract.sector == \"savings_bank\" and result.status == \"success\":\n"
        "            identity = reconcile_latest_savings_bank_funding_identity(db_path)\n"
        "            print(\n"
        "                \"funding identity reconciliation \"\n"
        "                f\"source={contract.source_id} latest_month={identity.latest_month} \"\n"
        "                f\"scanned={identity.scanned} eligible_unmapped={identity.eligible_unmapped} \"\n"
        "                f\"mapped={identity.mapped} unchanged_mapped={identity.unchanged_mapped} \"\n"
        "                f\"no_consensus={identity.no_consensus} \"\n"
        "                f\"excluded_aggregate={identity.excluded_aggregate}\",\n"
        "                flush=True,\n"
        "            )\n"
        "        if contract.sector == \"nh_local\" and result.status == \"success\":\n"
        "            identity = reconcile_agri_funding_identity(db_path)\n",
    )

    replace_once(
        "tests/test_savings_bank_funding_identity_reconciliation.py",
        "from datetime import UTC, date, datetime\n",
        "import calendar\nfrom datetime import UTC, date, datetime\n",
    )
    replace_once(
        "tests/test_savings_bank_funding_identity_reconciliation.py",
        "    period_end = date(year, mon, 31 if mon in {1, 3, 5, 7, 8, 10, 12} else 30)\n",
        "    period_end = date(year, mon, calendar.monthrange(year, mon)[1])\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
