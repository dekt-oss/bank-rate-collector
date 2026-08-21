"""Stage D1 우대조건 시장분석 계약 테스트."""

from rate_monitor.services.preference_intelligence_service import (
    build_preference_intelligence,
)


def _strategy_table(rows: list[list[object]]) -> dict:
    columns = [
        "sector",
        "institution",
        "product_id",
        "term_months",
        "max_rate",
        "preference",
        "preference_status",
        "preference_tags",
        "geo_basis",
        "region",
        "district",
    ]
    lookups = {
        "sector": ["savings_bank", "cu", "kfcc", "nh_local"],
        "institution": [
            "고려저축은행",
            "경쟁저축은행",
            "테스트신협",
            "테스트새마을금고",
            "테스트농협",
        ],
        "product_id": [f"p{i}" for i in range(1, 30)],
        "preference": [
            "모바일 가입 시 우대",
            "급여이체 시 우대",
            "우대조건 없음",
            "",
            "모바일 가입 및 급여이체 우대",
        ],
        "preference_status": ["present", "none", "missing"],
        "preference_tags": [
            "DIGITAL_CHANNEL",
            "SALARY_TRANSFER",
            "",
            "DIGITAL_CHANNEL SALARY_TRANSFER",
        ],
        "geo_basis": ["head_office", "outlet"],
        "region": ["부산", "서울"],
        "district": [None],
    }
    return {"columns": columns, "lookups": lookups, "rows": rows}


def _row(
    *,
    sector: int,
    institution: int,
    product_id: int,
    rate: float,
    preference: int,
    status: int,
    tags: int,
    term: int = 12,
    geo_basis: int = 0,
    region: int = 0,
) -> list[object]:
    return [
        sector,
        institution,
        product_id,
        term,
        rate,
        preference,
        status,
        tags,
        geo_basis,
        region,
        0,
    ]


def _scope(result: dict, sector: str, term: int = 12) -> dict:
    return next(
        item
        for item in result["scopes"]
        if item["sector"] == sector and item["term_months"] == term
    )


def _mutual_scope(result: dict, scope_key: str, term: int = 12) -> dict:
    return next(
        item
        for item in result["mutual_finance_scopes"]
        if item["scope_key"] == scope_key and item["term_months"] == term
    )


def test_category_share_uses_preference_bearing_products_only() -> None:
    rows: list[list[object]] = []
    # 10개 상품 중 실제 우대조건 보유 상품은 2개이고 둘 다 DIGITAL_CHANNEL이다.
    # 따라서 전체 상품 대비 20%가 아니라 우대조건 보유 상품 내부 침투율 100%가 맞다.
    rows.append(
        _row(
            sector=0,
            institution=0,
            product_id=0,
            rate=4.00,
            preference=0,
            status=0,
            tags=0,
        )
    )
    rows.append(
        _row(
            sector=0,
            institution=1,
            product_id=1,
            rate=3.90,
            preference=0,
            status=0,
            tags=0,
        )
    )
    for product_id in range(2, 10):
        rows.append(
            _row(
                sector=0,
                institution=1,
                product_id=product_id,
                rate=3.80 - product_id * 0.01,
                preference=2,
                status=1,
                tags=2,
            )
        )

    result = build_preference_intelligence(_strategy_table(rows))
    scope = _scope(result, "savings_bank")
    digital = next(
        item for item in scope["categories"] if item["code"] == "DIGITAL_CHANNEL"
    )

    assert result["version"] == "preference-intelligence-v2"
    assert result["category_denominator"] == "preference_bearing_products_present_only"
    assert result["category_composition_denominator"] == (
        "normalized_preference_category_occurrences_present_only"
    )
    assert result["effect_calibration"] == (
        "not_available_without_internal_performance_data"
    )
    assert scope["status"] == "supported"
    assert scope["coverage"]["known_preference_share"] == 1.0
    assert scope["coverage"]["preference_bearing_share_among_known"] == 0.2
    assert scope["coverage"]["explicit_none_share_among_known"] == 0.8
    assert scope["top_tier"]["offering_count"] == 1
    assert scope["top_tier"]["cutoff_rate"] == 4.0
    assert digital["market_count"] == 2
    assert digital["market_product_share"] == 1.0
    assert digital["top_tier_count"] == 1
    assert digital["top_tier_product_share"] == 1.0
    assert digital["top_tier_lift_pp"] == 0.0
    assert scope["our_company"]["preference_codes"] == ["DIGITAL_CHANNEL"]
    assert scope["our_company"]["raw_samples"] == ["모바일 가입 시 우대"]


def test_category_share_denominator_is_products_not_occurrences() -> None:
    # 우대조건 보유 3개 상품: P1=[DIGITAL,SALARY], P2=[DIGITAL], P3=[DIGITAL].
    # 구성비는 DIGITAL=3/4=75%, 상품 침투율은 DIGITAL=3/3=100%로 분모가 갈라진다.
    rows = [
        _row(
            sector=0,
            institution=0,
            product_id=0,
            rate=4.00,
            preference=4,
            status=0,
            tags=3,
        ),
        _row(
            sector=0,
            institution=1,
            product_id=1,
            rate=3.90,
            preference=0,
            status=0,
            tags=0,
        ),
        _row(
            sector=0,
            institution=1,
            product_id=2,
            rate=3.80,
            preference=0,
            status=0,
            tags=0,
        ),
    ]

    scope = _scope(build_preference_intelligence(_strategy_table(rows)), "savings_bank")
    digital = next(
        item for item in scope["categories"] if item["code"] == "DIGITAL_CHANNEL"
    )
    salary = next(
        item for item in scope["categories"] if item["code"] == "SALARY_TRANSFER"
    )

    assert scope["coverage"]["present_count"] == 3
    assert scope["category_occurrence_count"] == 4
    assert digital["market_share"] == 0.75
    assert salary["market_share"] == 0.25
    assert digital["market_product_share"] == 1.0
    assert salary["market_product_share"] == 0.3333
    assert sum(item["market_share"] for item in scope["categories"]) == 1.0
    assert sum(item["market_product_share"] for item in scope["categories"]) > 1.0
    assert digital["top_tier_product_share"] == 1.0
    assert salary["top_tier_product_share"] == 1.0
    assert digital["top_tier_lift_pp"] == 0.0
    assert salary["top_tier_lift_pp"] == 66.67
    assert digital["top_tier_composition_lift_pp"] == -25.0
    assert salary["top_tier_composition_lift_pp"] == 25.0


def test_missing_source_preference_is_not_counted_as_explicit_none() -> None:
    rows = [
        _row(
            sector=2,
            institution=3,
            product_id=0,
            rate=3.80,
            preference=0,
            status=0,
            tags=0,
            geo_basis=1,
        ),
    ]
    for product_id in range(1, 5):
        rows.append(
            _row(
                sector=2,
                institution=3,
                product_id=product_id,
                rate=3.70 - product_id * 0.01,
                preference=3,
                status=2,
                tags=2,
                geo_basis=1,
            )
        )

    result = build_preference_intelligence(_strategy_table(rows))
    scope = _scope(result, "kfcc")

    assert scope["coverage"] == {
        "total_offering_count": 5,
        "known_preference_count": 1,
        "present_count": 1,
        "none_count": 0,
        "missing_count": 4,
        "known_preference_share": 0.2,
        "preference_bearing_share_among_known": 1.0,
        "explicit_none_share_among_known": 0.0,
        "coverage_status": "low",
    }
    digital = next(
        item for item in scope["categories"] if item["code"] == "DIGITAL_CHANNEL"
    )
    assert digital["market_product_share"] == 1.0
    assert scope["coverage"]["missing_count"] == 4
    assert scope["coverage"]["none_count"] == 0


def test_mutual_finance_scope_pools_selected_sectors_before_top_tier() -> None:
    rows = [
        _row(
            sector=1,
            institution=2,
            product_id=0,
            rate=4.00,
            preference=0,
            status=0,
            tags=0,
            geo_basis=1,
        ),
        _row(
            sector=2,
            institution=3,
            product_id=1,
            rate=3.90,
            preference=1,
            status=0,
            tags=1,
            geo_basis=1,
        ),
        _row(
            sector=3,
            institution=4,
            product_id=2,
            rate=3.80,
            preference=2,
            status=1,
            tags=2,
            geo_basis=1,
        ),
    ]

    result = build_preference_intelligence(_strategy_table(rows))
    scope = _mutual_scope(result, "cu+kfcc+nh_local")

    assert scope["sector"] == "mutual_finance"
    assert scope["sectors"] == ["cu", "kfcc", "nh_local"]
    assert scope["coverage"]["total_offering_count"] == 3
    assert scope["coverage"]["present_count"] == 2
    assert scope["coverage"]["none_count"] == 1
    assert scope["coverage"]["preference_bearing_share_among_known"] == 0.6667
    assert scope["top_tier"]["offering_count"] == 1
    assert scope["top_tier"]["cutoff_rate"] == 4.0
    assert {item["sector"] for item in scope["source_coverage"]} == {
        "cu",
        "kfcc",
        "nh_local",
    }


def test_mutual_finance_payload_omits_duplicate_single_sector_scopes() -> None:
    rows = [
        _row(
            sector=1,
            institution=2,
            product_id=0,
            rate=4.00,
            preference=0,
            status=0,
            tags=0,
            geo_basis=1,
        )
    ]

    result = build_preference_intelligence(_strategy_table(rows))

    assert len(result["mutual_finance_scopes"]) == 16
    assert all(len(item["sectors"]) >= 2 for item in result["mutual_finance_scopes"])
    cu = _scope(result, "cu")
    assert cu["coverage"]["total_offering_count"] == 1
    assert cu["source_coverage"][0]["sector"] == "cu"


def test_same_strategy_offering_is_reduced_to_highest_rate_once() -> None:
    # product/term/geography가 같은 두 행은 Strategy 대표값 1개로 줄인다.
    rows = [
        _row(
            sector=0,
            institution=1,
            product_id=0,
            rate=3.50,
            preference=1,
            status=0,
            tags=1,
        ),
        _row(
            sector=0,
            institution=1,
            product_id=0,
            rate=3.70,
            preference=0,
            status=0,
            tags=0,
        ),
    ]

    scope = _scope(build_preference_intelligence(_strategy_table(rows)), "savings_bank")

    assert scope["coverage"]["total_offering_count"] == 1
    assert scope["top_tier"]["offering_count"] == 1
    assert scope["top_tier"]["cutoff_rate"] == 3.7
    assert [item["code"] for item in scope["categories"]] == ["DIGITAL_CHANNEL"]


def test_schema_unavailable_fails_closed() -> None:
    result = build_preference_intelligence({"columns": ["sector"], "rows": []})

    assert result["status"] == "schema_unavailable"
    assert "preference_tags" in result["missing_columns"]
    assert result["scopes"] == []
    assert result["mutual_finance_scopes"] == []
    assert result["effect_calibration"] == (
        "not_available_without_internal_performance_data"
    )
