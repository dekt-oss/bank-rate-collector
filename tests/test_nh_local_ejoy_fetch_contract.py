"""NH e-joy 보조 evidence 추출과 본 parser의 실패 경계를 고정한다."""

from datetime import date

import pytest

from rate_monitor.collectors.base import SchemaChangedError
from rate_monitor.collectors.nh_local import parser as nh
from rate_monitor.domain.enums import ProductType


def test_ejoy_auxiliary_extraction_fails_closed_without_detail_schema() -> None:
    options, warnings = nh.extract_ejoy_options("detail:SFDPW0163R:detail", brc="817020")

    assert options == []
    assert warnings == ["e-joy 상세표 캡션 없음: brc=817020"]


def test_primary_detail_parser_still_rejects_missing_detail_schema() -> None:
    outlet = nh.NhOutlet("817020", "가락농협", "부산광역시 강서구 가락대로 1459")

    with pytest.raises(SchemaChangedError, match="상세표 캡션"):
        nh.parse_detail(
            "detail:SFDPW0163R:detail",
            outlet=outlet,
            product_type=ProductType.TERM_DEPOSIT,
            as_of=date(2026, 8, 17),
        )
