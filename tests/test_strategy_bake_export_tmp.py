"""Stage A 베이크 전 템플릿 문자열의 일회성 baseline 계약.

최종 Stage A에서는 빌드 산출 HTML 계약으로 대체하고 이 파일은 삭제한다.
"""

import hashlib

from rate_monitor.services.site_service import (
    DEFAULT_STRATEGY_TEMPLATE,
    adapt_strategy_korea_map_template,
)
from rate_monitor.services.strategy_contract_service import adapt_strategy_template

_BASELINE_SHA256 = "2aa193e29048615e90771445644abcac001b3f5f1bdf08fbe07ce368ffc6c002"


def test_current_adapter_chain_matches_bake_baseline() -> None:
    source = DEFAULT_STRATEGY_TEMPLATE.read_text(encoding="utf-8")
    baked = adapt_strategy_korea_map_template(adapt_strategy_template(source))

    assert hashlib.sha256(baked.encode("utf-8")).hexdigest() == _BASELINE_SHA256
