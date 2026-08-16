"""Stage A 베이크 전 어댑터 출력과 새 source template의 바이트 계약."""

import hashlib

from rate_monitor.services.site_service import DEFAULT_STRATEGY_TEMPLATE

_PRE_BAKE_ADAPTER_OUTPUT_SHA256 = (
    "2aa193e29048615e90771445644abcac001b3f5f1bdf08fbe07ce368ffc6c002"
)


def test_baked_strategy_template_is_byte_identical_to_pre_bake_adapter_output() -> None:
    actual = hashlib.sha256(DEFAULT_STRATEGY_TEMPLATE.read_bytes()).hexdigest()

    assert actual == _PRE_BAKE_ADAPTER_OUTPUT_SHA256
