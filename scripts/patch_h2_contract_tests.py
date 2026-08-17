from pathlib import Path


def replace(path: str, old: str, new: str, *, expected: int = 1) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} matches for {old!r}, got {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace(
    "tests/test_strategy_contract_service.py",
    r'r.productId}\\0${term}',
    r'r.sector}\\0${r.productId}\\0${term}',
)
replace(
    "tests/test_strategy_dashboard.py",
    "if(aggregateCache.has(term))return aggregateCache.get(term)",
    "if(aggregateCache.has(cacheKey))return aggregateCache.get(cacheKey)",
)
replace(
    "tests/test_strategy_dashboard_refinement.py",
    'aria-label="시장 금리와 최근 변화 흐름"',
    'aria-label="저축은행 시장 금리와 최근 변화 흐름"',
)
replace(
    "tests/test_strategy_dashboard_refinement.py",
    "renderInsightsEnhanced();updateSim()",
    "renderInsightsEnhanced();applyModeVisibility();updateSim()",
)
replace(
    "tests/test_strategy_dashboard_ui_contract.py",
    r'r.productId}\\0${term}',
    r'r.sector}\\0${r.productId}\\0${term}',
)
replace(
    "tests/test_strategy_dashboard_ui_contract.py",
    "최근 정상 수집일 12개월 시장 최고 / 평균 / 고려저축은행 최고금리",
    "현재 평균은 선택 업권 기준 · 이력 추이는 저축은행 정상 수집일 기준",
)
replace(
    "tests/test_strategy_stage_e_ux.py",
    """    assert (
        '6·12·24·36개월 현재 평균 + 최근 정상 수집일 12개월 시장 최고 / 평균 / '
        '고려저축은행 최고금리' in html
    )""",
    """    assert (
        "현재 평균은 선택 업권 기준 · 이력 추이는 저축은행 정상 수집일 기준"
        in html
    )""",
)

print("updated H2 legacy contract tests")
