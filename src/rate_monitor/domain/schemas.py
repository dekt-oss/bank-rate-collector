"""수집기 공유 타입.

명세서 v3 §6.1을 승계하고, v3.1 §7의 행 단위 원본 추적 필드를 추가한다.
이 파일은 계약이다. 변경은 명세 갱신을 먼저 거친다.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class CollectionRequest:
    source_id: str
    regions: tuple[str, ...] = ()
    product_types: tuple[str, ...] = ()
    terms: tuple[int, ...] = ()
    channels: tuple[str, ...] = ()
    as_of: date | None = None
    input_files: tuple[str, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawArtifactData:
    artifact_type: str
    content: bytes
    filename: str
    request_meta: dict[str, Any]
    schema_fingerprint: str
    source_role: str
    trust_level: str


@dataclass(frozen=True)
class ParsedRateRow:
    source_id: str
    source_role: str
    trust_level: str

    # 권역. 행이 스스로 밝힌다.
    #
    # 예전에는 entity_service가 rate_scope로 되짚어 추측했다. 저축은행 하나만
    # 있을 때는 맞았지만 원천이 늘면 곧바로 틀린다. 예를 들어 새마을금고 행은
    # rate_scope=institution이라 그 추측이 bank를 돌려주고, 그 값이
    # make_org_key에 들어가 "bank:1203" 같은 잘못된 식별키를 만든다.
    # 권역은 파서가 아는 사실이므로 여기서 받는다 (Sector 열거형 값).
    sector: str

    source_institution_key: str | None
    source_outlet_key: str | None
    source_product_key: str | None
    institution_name: str
    outlet_name: str | None
    institution_type: str | None
    sido: str | None
    sigungu: str | None
    address: str | None
    product_type: str
    product_name: str
    term_months: int | None
    term_days: int | None
    join_channel: str
    interest_method: str
    payment_method: str | None
    amount_min: int | None
    amount_max: int | None
    customer_scope: str | None
    availability_scope: str
    rate_scope: str
    # DECIMAL(7,4) 계약 (v3 §5.9). float로 낮추면 저장 계층과 타입이 어긋난다.
    base_rate: Decimal | None
    max_rate: Decimal | None
    preference_raw: str
    source_row_ref: str

    # v3.1 §7 — 행 단위 원본 추적
    base_source_locator: str
    source_record_hash: str
    option_source_locator: str | None = None

    # v3.1 §7.3 — 시각 분리. 원천 기준일이 없으면 None으로 둔다.
    # collected_at은 오케스트레이터가 채우므로 여기 없다.
    source_effective_at: date | None = None

    # 검증 결과. 파싱 실패 행도 버리지 않고 상태를 달아 반환한다 (v3 §6.2).
    validation_status: str = "valid"
    validation_message: str | None = None

    extra: dict[str, Any] = field(default_factory=dict)

    # 이 기관의 점포 명부.
    #
    # 금리가 기관 단위인 원천에서 필요하다. 새마을금고가 그렇다 — 금리는
    # 금고(gmgoCd)마다 하나인데 주소는 점포마다 다르고, 한 금고가 두 구에
    # 점포를 두기도 한다. 대표 점포 하나만 붙이면 나머지 구에서 그 금고가
    # 사라진다.
    #
    # 같은 기관의 행마다 같은 명부를 실어 나르면 낭비이므로 **아티팩트당
    # 첫 행에만** 채운다. 나머지 행은 빈 튜플이다.
    #
    # 각 항목의 키: source_outlet_key, name, address, phone
    outlets: tuple[dict[str, Any], ...] = ()


class SourceAdapter(Protocol):
    """수집원 어댑터 계약.

    오케스트레이터가 실제로 요구하는 것을 전부 적는다. 예전에는 `fetch`와
    `parse`만 선언돼 있었지만 `collection_service`는 `parse_with_warnings`를
    부르고 `ensure_source`는 아래 메타데이터를 읽는다. 선언과 실제가 어긋나
    있으면 새 어댑터를 만들 때 무엇을 채워야 하는지 알 수 없다.
    """

    source_id: str

    # ensure_source가 sources 행을 만들 때 읽는 값들.
    # 예전에는 finlife 값이 collection_service에 하드코딩돼 있었다.
    source_role: str
    trust_level: str
    sector: str
    mode: str
    priority: int
    source_name: str
    base_reference: str
    policy_status: str
    coverage_status: str

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]: ...

    def parse(self, artifact: RawArtifactData) -> list[ParsedRateRow]: ...

    def parse_with_warnings(
        self, artifact: RawArtifactData
    ) -> tuple[list[ParsedRateRow], list[str]]: ...
