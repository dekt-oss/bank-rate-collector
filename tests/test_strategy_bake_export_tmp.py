"""Stage A 베이크 baseline을 CI 로그로 정확히 회수하기 위한 일회성 테스트.

최종 Stage A diff에서는 삭제한다.
"""

import base64
import hashlib
import zlib

from rate_monitor.services.site_service import (
    DEFAULT_STRATEGY_TEMPLATE,
    adapt_strategy_korea_map_template,
)
from rate_monitor.services.strategy_contract_service import adapt_strategy_template


def test_export_baked_strategy_template() -> None:
    source = DEFAULT_STRATEGY_TEMPLATE.read_text(encoding="utf-8")
    baked = adapt_strategy_korea_map_template(adapt_strategy_template(source))
    payload = base64.b64encode(zlib.compress(baked.encode("utf-8"), 9)).decode("ascii")
    print("BAKE_SHA256=" + hashlib.sha256(baked.encode("utf-8")).hexdigest())
    print("BAKE_ZLIB_BASE64=" + payload)
    raise AssertionError("BAKE_EXPORT_ONLY")
