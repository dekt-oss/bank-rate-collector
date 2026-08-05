"""수집기 공유 타입.

명세서 v3 §6.1을 승계하고, v3.1 §7의 행 단위 원본 추적 필드를 추가한다.
이 파일은 계약이다. 변경은 명세 갱신을 먼저 거친다.
"""

from dataclasses import dataclass, field
from datetime import date
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
    base_rate: float | None
    max_rate: float | None
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


class SourceAdapter(Protocol):
    source_id: str

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]: ...

    def parse(self, artifact: RawArtifactData) -> list[ParsedRateRow]: ...
