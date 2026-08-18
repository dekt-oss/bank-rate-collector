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
        "sector": ["savings_bank", "kfcc"],
        "institution": ["고려저축은행", "경쟁저축은행", "테스트새마을금고"],
        "product_id": [f"p{i}" for i in range(1, 20)],
        "preference": [
            "모바일 가입 시 우대",
            "급여이체 시 우대",
            "우대조건 없음",
            "",
        ],
        "preference_status": ["present", "none", "missing"],
        "preference_tags": ["DIGITAL_CHANNEL", "SALARY_TRANSFER", ""],
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


def test_top_tier_lift_is_descriptive_and_uses_known_preference_denominator() -> None:
    rows: list[list[object]] = []
    # 10개 상품 중 DIGITAL_CHANNEL은 2개다. 그중 최고금리 상품이 DIGITAL이다.
    # top ceil(10%) = 1개이므로 market 20%, top 100%, lift +80%p가 된다.
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

    assert result["effect_calibration"] == (
        "not_available_without_internal_performance_data"
    )
    assert scope["status"] == "supported"
    assert scope["coverage"]["known_preference_share"] == 1.0
    assert scope["top_tier"]["offering_count"] == 1
    assert scope["top_tier"]["cutoff_rate"] == 4.0
    assert digital["market_count"] == 2
    assert digital["market_share"] == 0.2
    assert digital["top_tier_count"] == 1
    assert digital["top_tier_share"] == 1.0
    assert digital["top_tier_lift_pp"] == 80.0
    assert scope["our_company"]["preference_codes"] == ["DIGITAL_CHANNEL"]
    assert scope["our_company"]["raw_samples"] == ["모바일 가입 시 우대"]


def test_missing_source_preference_is_not_counted_as_explicit_none() -> None:
    rows = [
        _row(
            sector=1,
            institution=2,
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
                sector=1,
                institution=2,
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
        "coverage_status": "low",
    }
    digital = next(
        item for item in scope["categories"] if item["code"] == "DIGITAL_CHANNEL"
    )
    assert digital["market_share"] == 1.0
    assert scope["coverage"]["missing_count"] == 4
    assert scope["coverage"]["none_count"] == 0


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
    assert result["effect_calibration"] == (
        "not_available_without_internal_performance_data"
    )
