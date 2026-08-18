"""전략 화면 전용 stable product identity / universe 계약.

공개 검색 화면의 canonical ``base_rate``/``max_rate`` 계약은 그대로 보존한다.
전략 Release Gate가 켜진 빌드에서만 현재 대시보드에 이미 수집된 금리 행을
``수집 데이터 기준 최고금리``로 다시 해석한다.

전략 비교값은 다음 우선순위다.

1. 원천/collector가 제공한 ``max_rate``
2. 농·축협의 경우 같은 현재 스냅샷 안에서 안전하게 연결되는
   ``기본금리 + e-joy 인터넷예금 우대금리``
3. 그 외에는 실제 수집된 ``base_rate``

3번은 canonical ``max_rate``를 채우는 규칙이 아니다. 전략 화면에서 "현재
수집기로 확인 가능한 가장 높은 금리"를 비교하기 위한 명시적 fallback이다.
따라서 공개 ``data/table.json``의 ``max_rate`` 의미는 바뀌지 않는다.
"""

import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from rate_monitor.services.dashboard_service import DashboardBuildError

PRODUCT_ID_COLUMN = "product_id"
STRATEGY_RATE_BASIS_COLUMN = "strategy_rate_basis"
STRATEGY_SECTOR = "savings_bank"  # 기존 caller 호환용 기본 업권
STRATEGY_PRODUCT_TYPE = "term_deposit"
STRATEGY_TERMS = frozenset({6, 12, 24, 36})
STRATEGY_CANDIDATE_SECTORS = ("savings_bank", "cu", "kfcc", "nh_local")
# 이름은 기존 caller/test 호환용으로 유지한다. 이제 네 업권 모두 strategy rate를
# 만들 수 있으며 canonical max_rate capability와 같은 뜻이 아니다.
STRATEGY_MAX_RATE_ENABLED_SECTORS = frozenset(STRATEGY_CANDIDATE_SECTORS)
STRATEGY_SOURCE_MAX_RATE_SECTORS = frozenset({"savings_bank", "cu", "nh_local"})
STRATEGY_SECTOR_LABELS = {
    "savings_bank": "저축은행",
    "cu": "신협",
    "kfcc": "새마을금고",
    "nh_local": "농·축협",
}
STRATEGY_RATE_EVIDENCE = {
    "savings_bank": "source_max_then_collected_base",
    "cu": "source_max_then_collected_base",
    "kfcc": "official_central_collected_base_rate_ceiling",
    "nh_local": "source_max_or_current_snapshot_ejoy_composition_then_collected_base",
}
STRATEGY_RATE_BASIS_SOURCE_MAX = "source_max_rate"
STRATEGY_RATE_BASIS_NH_EJOY = "nh_ejoy_base_plus_add"
STRATEGY_RATE_BASIS_COLLECTED_BASE = "collected_base_rate"
STRATEGY_RATE_BASIS_PRIORITY = {
    STRATEGY_RATE_BASIS_SOURCE_MAX: 3,
    STRATEGY_RATE_BASIS_NH_EJOY: 2,
    STRATEGY_RATE_BASIS_COLLECTED_BASE: 1,
}

NH_EJOY_PRODUCT = "e-joy 인터넷예금 우대금리"
NH_EJOY_APPLICABILITY_NOTE = (
    "- 대상예금 <거치식> 정기예탁금, 복리식 정기예탁금 "
    "<적립식> 정기적금, 자유적립 적금, 자유로 부금 "
    "- 상품별 금리 + 우대금리 적용"
)
NH_EJOY_TERMS = (1, 12, 24, 36)
NH_TERM_DEPOSIT_TARGETS = frozenset({"정기예탁금", "복리식정기예탁금"})

_IDENTITY_KEY_COLUMNS = (
    "source_id",
    "institution",
    "product",
    "product_type",
    "term_months",
    "payment_method",
    "interest_method",
    "join_channel",
)


def _decode(table: dict[str, Any], column: str, value: Any) -> Any:
    lookup = (table.get("lookups") or {}).get(column)
    if lookup is None or value is None:
        return value
    return lookup[value]


def _row_key(table: dict[str, Any], row: list[Any]) -> tuple[Any, ...]:
    columns = {name: index for index, name in enumerate(table.get("columns") or [])}
    return tuple(
        _decode(table, name, row[columns[name]]) for name in _IDENTITY_KEY_COLUMNS
    )


def _rate_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _rate_present(value: Any) -> bool:
    return _rate_float(value) is not None


def _sorted_decoded_values(
    table: dict[str, Any],
    rows: list[list[Any]],
    source_columns: dict[str, int],
    column: str,
) -> list[str]:
    index = source_columns.get(column)
    if index is None:
        return []
    values = {
        str(value)
        for row in rows
        if (value := _decode(table, column, row[index])) not in (None, "")
    }
    return sorted(values)


def _lookup_index(lookups: dict[str, list[Any]], column: str, value: Any) -> int:
    values = lookups.setdefault(column, [])
    try:
        return values.index(value)
    except ValueError:
        values.append(value)
        return len(values) - 1


def _decoded_location_key(
    table: dict[str, Any],
    row: list[Any],
    source_columns: dict[str, int],
) -> tuple[Any, ...]:
    # display 이름 하나만으로 NH를 연결하지 않는다. 현재 대시보드 스냅샷의
    # 기관/점포/시도/구·군 조합이 겹치면 option 행 수가 2배가 되어 fail closed한다.
    fields = ("source_id", "institution", "outlet", "region", "district")
    return tuple(
        _decode(table, field, row[source_columns[field]])
        if field in source_columns
        else None
        for field in fields
    )


def _nh_ejoy_options(
    table: dict[str, Any],
    source_columns: dict[str, int],
) -> dict[tuple[Any, ...], dict[int, tuple[float, list[Any]]]]:
    required = {
        "sector",
        "product",
        "product_type",
        "term_months",
        "base_rate",
        "preference",
    }
    if not required.issubset(source_columns):
        return {}

    grouped: dict[
        tuple[Any, ...],
        dict[int, list[tuple[float, list[Any]]]],
    ] = defaultdict(lambda: defaultdict(list))
    for row in table.get("rows") or []:
        if _decode(table, "sector", row[source_columns["sector"]]) != "nh_local":
            continue
        if (
            _decode(table, "product_type", row[source_columns["product_type"]])
            != STRATEGY_PRODUCT_TYPE
        ):
            continue
        if _decode(table, "product", row[source_columns["product"]]) != NH_EJOY_PRODUCT:
            continue
        if (
            _decode(table, "preference", row[source_columns["preference"]])
            != NH_EJOY_APPLICABILITY_NOTE
        ):
            continue
        term = row[source_columns["term_months"]]
        rate = _rate_float(row[source_columns["base_rate"]])
        if term not in NH_EJOY_TERMS or rate is None or rate < 0:
            continue
        grouped[_decoded_location_key(table, row, source_columns)][int(term)].append(
            (rate, row)
        )

    validated: dict[tuple[Any, ...], dict[int, tuple[float, list[Any]]]] = {}
    for key, by_term in grouped.items():
        # 전국 census에서 확인된 네 구간이 현재 snapshot에서도 각각 정확히
        # 한 행이어야 한다. 동명이 기관이 같은 지역키에서 겹치면 여기서 닫힌다.
        if set(by_term) != set(NH_EJOY_TERMS):
            continue
        if any(len(by_term[term]) != 1 for term in NH_EJOY_TERMS):
            continue
        validated[key] = {term: by_term[term][0] for term in NH_EJOY_TERMS}
    return validated


def _nh_ejoy_option(
    options: dict[int, tuple[float, list[Any]]],
    term: int,
) -> tuple[float, list[Any]] | None:
    if term < 1:
        return None
    lower = 1 if term < 12 else 12 if term < 24 else 24 if term < 36 else 36
    return options.get(lower)


def _copy_lookup_field(
    *,
    table: dict[str, Any],
    source_columns: dict[str, int],
    lookups: dict[str, list[Any]],
    target: list[Any],
    source: list[Any],
    column: str,
) -> None:
    index = source_columns.get(column)
    if index is None:
        return
    value = _decode(table, column, source[index])
    if column in (table.get("lookups") or {}):
        target[index] = _lookup_index(lookups, column, value)
    else:
        target[index] = value


def _representative_key(
    table: dict[str, Any],
    row: list[Any],
    source_columns: dict[str, int],
) -> tuple[Any, ...]:
    sector = _decode(table, "sector", row[source_columns["sector"]])
    product_id = (
        _decode(table, PRODUCT_ID_COLUMN, row[source_columns[PRODUCT_ID_COLUMN]])
        if PRODUCT_ID_COLUMN in source_columns
        else None
    )
    if product_id is None:
        # legacy/test caller. 신규 Strategy build는 product_id를 직접 운반한다.
        product_id = (
            _decode(table, "institution", row[source_columns["institution"]])
            if "institution" in source_columns
            else None,
            _decode(table, "product", row[source_columns["product"]])
            if "product" in source_columns
            else None,
        )
    return (
        sector,
        product_id,
        row[source_columns["term_months"]],
        _decode(table, "geo_basis", row[source_columns["geo_basis"]])
        if "geo_basis" in source_columns
        else None,
        _decode(table, "region", row[source_columns["region"]])
        if "region" in source_columns
        else None,
        _decode(table, "district", row[source_columns["district"]])
        if "district" in source_columns
        else None,
    )


def _derive_strategy_rows(table: dict[str, Any]) -> dict[str, Any]:
    """현재 dashboard table만으로 Strategy 비교금리를 만든다.

    입력 table을 절대 수정하지 않는다. ``max_rate``를 덮는 것은 반환되는
    Strategy 전용 복사본뿐이며, basis 열에 어떤 규칙으로 만든 값인지 남긴다.
    """
    columns = list(table.get("columns") or [])
    source_columns = {name: index for index, name in enumerate(columns)}
    required = {
        "sector",
        "product_type",
        "term_months",
        "base_rate",
        "max_rate",
        "product",
    }
    missing = sorted(required.difference(source_columns))
    if missing:
        raise DashboardBuildError(
            "전략 비교금리에 필요한 table 열이 없다: " + ", ".join(missing)
        )

    lookups = {
        name: list(values) for name, values in (table.get("lookups") or {}).items()
    }
    lookups[STRATEGY_RATE_BASIS_COLUMN] = []
    basis_index = len(columns)
    derived_columns = [*columns, STRATEGY_RATE_BASIS_COLUMN]
    nh_options = _nh_ejoy_options(table, source_columns)
    candidates: list[list[Any]] = []

    for source_row in table.get("rows") or []:
        sector = _decode(table, "sector", source_row[source_columns["sector"]])
        if sector not in STRATEGY_MAX_RATE_ENABLED_SECTORS:
            continue
        product_type = _decode(
            table, "product_type", source_row[source_columns["product_type"]]
        )
        term = source_row[source_columns["term_months"]]
        if product_type != STRATEGY_PRODUCT_TYPE or term not in STRATEGY_TERMS:
            continue

        product = _decode(table, "product", source_row[source_columns["product"]])
        if sector == "nh_local" and product == NH_EJOY_PRODUCT:
            # 가산율 자체는 가입상품이 아니다.
            continue

        row = list(source_row)
        source_max = _rate_float(row[source_columns["max_rate"]])
        base = _rate_float(row[source_columns["base_rate"]])
        strategy_rate: float | None = None
        basis: str | None = None

        if source_max is not None:
            strategy_rate = source_max
            basis = STRATEGY_RATE_BASIS_SOURCE_MAX
        elif (
            sector == "nh_local"
            and product in NH_TERM_DEPOSIT_TARGETS
            and base is not None
        ):
            options = nh_options.get(
                _decoded_location_key(table, source_row, source_columns)
            )
            option = _nh_ejoy_option(options, int(term)) if options else None
            if option is not None:
                add_rate, option_row = option
                strategy_rate = base + add_rate
                basis = STRATEGY_RATE_BASIS_NH_EJOY
                # 합산값은 인터넷 우대조건 적용값이므로 Strategy 복사본만
                # 채널/우대 근거를 e-joy 행으로 맞춘다.
                if "join_channel" in source_columns:
                    row[source_columns["join_channel"]] = _lookup_index(
                        lookups, "join_channel", "internet"
                    )
                for field in ("preference", "preference_status", "preference_tags"):
                    _copy_lookup_field(
                        table=table,
                        source_columns=source_columns,
                        lookups=lookups,
                        target=row,
                        source=option_row,
                        column=field,
                    )

        if strategy_rate is None and base is not None:
            strategy_rate = base
            basis = STRATEGY_RATE_BASIS_COLLECTED_BASE

        if strategy_rate is None or basis is None:
            continue

        row[source_columns["max_rate"]] = strategy_rate
        row.append(_lookup_index(lookups, STRATEGY_RATE_BASIS_COLUMN, basis))
        candidates.append(row)

    # 브라우저가 다시 stable product 대표값을 고르지만, payload를 불필요하게
    # 키우지 않도록 같은 상품/기간/지역관측 안에서는 여기서 한 번 줄인다.
    best: dict[tuple[Any, ...], list[Any]] = {}
    effective_index = source_columns.get("source_effective_at")
    basis_table = {"lookups": lookups}
    for row in candidates:
        key = _representative_key(table, row, source_columns)
        old = best.get(key)
        if old is None:
            best[key] = row
            continue
        new_rate = float(row[source_columns["max_rate"]])
        old_rate = float(old[source_columns["max_rate"]])
        new_basis = _decode(
            basis_table, STRATEGY_RATE_BASIS_COLUMN, row[basis_index]
        )
        old_basis = _decode(
            basis_table, STRATEGY_RATE_BASIS_COLUMN, old[basis_index]
        )
        new_fresh = (
            str(_decode(table, "source_effective_at", row[effective_index]) or "")
            if effective_index is not None
            else ""
        )
        old_fresh = (
            str(_decode(table, "source_effective_at", old[effective_index]) or "")
            if effective_index is not None
            else ""
        )
        score = (
            new_rate,
            STRATEGY_RATE_BASIS_PRIORITY.get(str(new_basis), 0),
            new_fresh,
        )
        old_score = (
            old_rate,
            STRATEGY_RATE_BASIS_PRIORITY.get(str(old_basis), 0),
            old_fresh,
        )
        if score > old_score:
            best[key] = row

    return {
        **table,
        "columns": derived_columns,
        "lookups": lookups,
        "rows": list(best.values()),
    }


def strategy_universe_metadata(table: dict[str, Any]) -> dict[str, Any]:
    """Strategy 전용 수집 데이터 기준 최고금리 coverage를 만든다."""
    columns = list(table.get("columns") or [])
    source_columns = {name: index for index, name in enumerate(columns)}
    required = {"sector", "product_type", "term_months", "max_rate"}
    missing = sorted(required.difference(source_columns))
    if missing:
        raise DashboardBuildError(
            "전략 universe에 필요한 table 열이 없다: " + ", ".join(missing)
        )

    by_sector: dict[str, list[list[Any]]] = {
        sector: [] for sector in STRATEGY_CANDIDATE_SECTORS
    }
    for row in table.get("rows") or []:
        sector = _decode(table, "sector", row[source_columns["sector"]])
        if sector not in by_sector:
            continue
        product_type = _decode(
            table, "product_type", row[source_columns["product_type"]]
        )
        term = row[source_columns["term_months"]]
        if product_type == STRATEGY_PRODUCT_TYPE and term in STRATEGY_TERMS:
            by_sector[sector].append(row)

    max_index = source_columns["max_rate"]
    basis_index = source_columns.get(STRATEGY_RATE_BASIS_COLUMN)
    effective_index = source_columns.get("source_effective_at")
    sectors: dict[str, dict[str, Any]] = {}

    for sector in STRATEGY_CANDIDATE_SECTORS:
        rows = by_sector[sector]
        rate_rows = sum(_rate_present(row[max_index]) for row in rows)
        latest_effective_at = None
        if effective_index is not None:
            values = [
                str(value)
                for row in rows
                if (
                    value := _decode(
                        table, "source_effective_at", row[effective_index]
                    )
                )
                not in (None, "")
            ]
            if values:
                latest_effective_at = max(values)

        basis_counts: Counter[str] = Counter()
        if basis_index is not None:
            for row in rows:
                basis = _decode(
                    table, STRATEGY_RATE_BASIS_COLUMN, row[basis_index]
                )
                if basis:
                    basis_counts[str(basis)] += 1

        terms: dict[str, dict[str, Any]] = {}
        for term in sorted(STRATEGY_TERMS):
            term_rows = [
                row for row in rows if row[source_columns["term_months"]] == term
            ]
            term_rate_rows = sum(_rate_present(row[max_index]) for row in term_rows)
            terms[str(term)] = {
                "rows": len(term_rows),
                "max_rate_rows": term_rate_rows,  # compatibility alias
                "strategy_rate_rows": term_rate_rows,
                "coverage_ratio": (
                    round(term_rate_rows / len(term_rows), 6) if term_rows else None
                ),
                "selectable": term_rate_rows > 0,
            }

        state = (
            "supported" if rate_rows else ("no_rows" if not rows else "no_rate_data")
        )
        sectors[sector] = {
            "label": STRATEGY_SECTOR_LABELS[sector],
            "state": state,
            "max_rate_capability": sector in STRATEGY_SOURCE_MAX_RATE_SECTORS,
            "strategy_rate_capability": True,
            "selectable": rate_rows > 0,
            "rows": len(rows),
            "max_rate_rows": rate_rows,  # compatibility alias
            "strategy_rate_rows": rate_rows,
            "coverage_ratio": round(rate_rows / len(rows), 6) if rows else None,
            "latest_source_effective_at": latest_effective_at,
            "geo_basis": _sorted_decoded_values(
                table, rows, source_columns, "geo_basis"
            ),
            "rate_scope": _sorted_decoded_values(
                table, rows, source_columns, "rate_scope"
            ),
            "availability_scope": _sorted_decoded_values(
                table, rows, source_columns, "availability_scope"
            ),
            "evidence": STRATEGY_RATE_EVIDENCE[sector],
            "rate_basis_counts": dict(sorted(basis_counts.items())),
            "blocked_reason": None,
            "terms": terms,
        }

    return {
        "metric_basis": "collected_best_rate",
        "metric_label": "수집 데이터 기준 최고금리",
        "default_mode": "savings_bank",
        "candidate_sectors": list(STRATEGY_CANDIDATE_SECTORS),
        "published_sectors": list(STRATEGY_CANDIDATE_SECTORS),
        "base_rate_fallback": True,
        "canonical_max_rate_unchanged": True,
        "strategy_rate_policy": (
            "source_max_then_declared_additive_composition_then_collected_base"
        ),
        "sectors": sectors,
    }


def slice_strategy_table(table: dict[str, Any]) -> dict[str, Any]:
    """canonical table 복사본에 Strategy 비교금리만 파생해 발행한다."""
    derived = _derive_strategy_rows(table)
    universe = strategy_universe_metadata(derived)
    return {**derived, "strategy_universe": universe}


def _product_id_index(db_path: Path) -> dict[tuple[Any, ...], str | None]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT
                r.source_id,
                i.canonical_name,
                p.name,
                p.product_type,
                v.term_months,
                v.payment_method,
                v.interest_method,
                v.join_channel,
                p.id
            FROM rate_observations o
            JOIN collection_runs r ON r.id = o.run_id
            JOIN product_variants v ON v.id = o.variant_id
            JOIN products p ON p.id = v.product_id
            JOIN institutions i ON i.id = p.institution_id
            WHERE o.valid_to IS NULL
              AND o.validation_status != 'error'
            """
        ).fetchall()
    finally:
        conn.close()

    candidates: dict[tuple[Any, ...], set[str]] = {}
    for row in rows:
        key = tuple(row[:-1])
        candidates.setdefault(key, set()).add(str(row[-1]))
    return {
        key: next(iter(ids)) if len(ids) == 1 else None
        for key, ids in candidates.items()
    }


def augment_strategy_table(
    db_path: Path, table: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    """전략 slice에 압축 ``product_id`` 열을 추가한다.

    신규 site build는 DB query에서 stable id를 직접 운반한다. 과거 caller를 위해
    display-key 재조인 경로는 남겨 두지만, 이미 ``product_id``가 있으면 재조인하지
    않는다. 이 경우에도 null id는 즉시 build 실패다.
    """
    columns = list(table.get("columns") or [])
    if PRODUCT_ID_COLUMN in columns:
        product_id_index = columns.index(PRODUCT_ID_COLUMN)
        rows = table.get("rows") or []
        unmatched = sum(row[product_id_index] is None for row in rows)
        if unmatched:
            raise DashboardBuildError(
                "전략 비교상품 stable product_id 직접 전달 실패: "
                f"{unmatched}행"
            )
        return table, {"matched": len(rows), "unmatched": 0}

    source_columns = {name: index for index, name in enumerate(columns)}
    required = set(_IDENTITY_KEY_COLUMNS) | {"sector"}
    missing = sorted(required.difference(source_columns))
    if missing:
        raise DashboardBuildError(
            "전략 stable identity에 필요한 table 열이 없다: " + ", ".join(missing)
        )

    product_ids = _product_id_index(db_path)
    id_lookup: list[str] = []
    id_positions: dict[str, int] = {}
    rows: list[list[Any]] = []
    target_unmatched = 0
    matched = 0

    for source_row in table.get("rows") or []:
        row = list(source_row)
        product_id = product_ids.get(_row_key(table, row))
        if product_id is not None:
            matched += 1
            if product_id not in id_positions:
                id_positions[product_id] = len(id_lookup)
                id_lookup.append(product_id)
            row.append(id_positions[product_id])
        else:
            row.append(None)
            sector = _decode(table, "sector", row[source_columns["sector"]])
            product_type = _decode(
                table, "product_type", row[source_columns["product_type"]]
            )
            term = row[source_columns["term_months"]]
            if (
                sector in STRATEGY_MAX_RATE_ENABLED_SECTORS
                and product_type == STRATEGY_PRODUCT_TYPE
                and term in STRATEGY_TERMS
            ):
                target_unmatched += 1
        rows.append(row)

    if target_unmatched:
        raise DashboardBuildError(
            "전략 비교상품 stable product_id 매칭 실패: "
            f"{target_unmatched}행"
        )

    lookups = dict(table.get("lookups") or {})
    lookups[PRODUCT_ID_COLUMN] = id_lookup
    return (
        {
            **table,
            "columns": [*columns, PRODUCT_ID_COLUMN],
            "lookups": lookups,
            "rows": rows,
        },
        {"matched": matched, "unmatched": len(rows) - matched},
    )
