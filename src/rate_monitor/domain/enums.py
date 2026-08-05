"""도메인 열거형.

명세서 v3 §4를 그대로 승계한다 (v3.1 §2). 값 문자열을 바꾸면 DB에 저장된
기존 레코드와 어긋나므로, 변경은 명세 갱신과 마이그레이션을 먼저 거친다.
"""

from enum import StrEnum


class Sector(StrEnum):
    BANK = "bank"
    SAVINGS_BANK = "savings_bank"
    KFCC = "kfcc"
    CU = "cu"
    NH_LOCAL = "nh_local"


class ProductType(StrEnum):
    TERM_DEPOSIT = "term_deposit"
    INSTALLMENT_SAVINGS = "installment_savings"
    FLEXIBLE_SAVINGS = "flexible_savings"
    DEMAND_DEPOSIT = "demand_deposit"
    OTHER = "other"


class JoinChannel(StrEnum):
    BRANCH = "branch"
    INTERNET = "internet"
    MOBILE = "mobile"
    TELEPHONE = "telephone"
    AGENT = "agent"
    ANY = "any"
    UNKNOWN = "unknown"


class InterestMethod(StrEnum):
    SIMPLE = "simple"
    COMPOUND = "compound"
    UNKNOWN = "unknown"


class AvailabilityScope(StrEnum):
    NATIONWIDE = "nationwide"
    LOCAL_MEMBERS = "local_members"
    WORKPLACE_MEMBERS = "workplace_members"
    SPECIFIC_REGION = "specific_region"
    UNKNOWN = "unknown"


class RateScope(StrEnum):
    NATIONWIDE = "nationwide"
    INSTITUTION = "institution"
    OUTLET = "outlet"
    HEAD_OFFICE_REFERENCE = "head_office_reference"
    UNKNOWN = "unknown"


class CollectionMode(StrEnum):
    API = "api"
    HTTP = "http"
    BROWSER = "browser"
    FILE = "file"
    MANUAL = "manual"


class SourceRole(StrEnum):
    PRIMARY_OFFICIAL = "primary_official"
    SECONDARY_OFFICIAL = "secondary_official"
    REFERENCE_THIRD_PARTY = "reference_third_party"
    MANUAL_OFFICIAL_IMPORT = "manual_official_import"
    MANUAL_OVERRIDE = "manual_override"


class TrustLevel(StrEnum):
    OFFICIAL_DIRECT = "official_direct"
    OFFICIAL_IMPORTED = "official_imported"
    THIRD_PARTY_REFERENCE = "third_party_reference"
    USER_ENTERED = "user_entered"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    NO_CHANGE = "no_change"
    BLOCKED = "blocked"
    SCHEMA_CHANGED = "schema_changed"
    FAILED = "failed"


class ValidationStatus(StrEnum):
    VALID = "valid"
    WARNING = "warning"
    ERROR = "error"
    REVIEWED = "reviewed"


class SchemaChangeLevel(StrEnum):
    """스키마 변경 등급 (v3.1 §8).

    v3는 모든 구조 변화를 SchemaChangedError로 처리해 선택 필드 추가에도
    수집이 멈출 수 있었다. 등급을 나눠 호환 변경은 통과시킨다.
    """

    COMPATIBLE = "compatible_schema_change"
    BREAKING = "breaking_schema_change"
