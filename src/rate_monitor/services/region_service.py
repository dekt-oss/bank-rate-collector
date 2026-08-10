"""지역을 한 곳에서 정한다 (v4 §4).

같은 규칙이 두 군데 흩어져 있었다. 수집할 때는 `kfcc/parser.split_region`이
주소를 토막 내고, 화면을 그릴 때는 `dashboard_service`가 SQL에서 같은 일을
다시 했다. 한쪽만 고치면 수집한 값과 보이는 값이 달라진다.

**지역은 한 종류가 아니다** (v4 §4.1). 원천마다 "부산"이라는 말의 근거가
다르다.

    새마을금고   점포 주소에서 뽑았다        → 그 구에 실제로 점포가 있다
    신협         조회조건이 부산이었다        → 점포 주소는 모른다
    저축은행     본점이 부산이다              → 부산 지점 금리가 아니다
    시중은행     전국 공시다                  → 지역이라는 말이 성립하지 않는다

이 넷을 같은 칸에 넣고 "지역"이라고 부르면, 화면에서 부산 중구를 고른
사람이 네 가지 다른 뜻을 하나로 본다. `GeoBasis`가 그 차이를 남긴다.
"""

from typing import NamedTuple

from rate_monitor.domain.enums import GeoBasis


class RegionFields(NamedTuple):
    """기관·점포 행에 저장하는 지역 네 칸 (v4 §4.2).

    `confidence`는 "얼마나 믿는가"가 아니라 **어디까지 좁혀 말할 수 있는가**다.

        high     구·군까지. 점포 주소에서 나왔다
        medium   시도까지. 본점 기준이거나 조회조건이거나 주소가 시도뿐이다
        none     주소가 없다
    """

    sido: str | None
    sigungu: str | None
    basis: GeoBasis
    confidence: str


# 시도 표기를 맞춘다.
#
# 같은 곳이 원천마다 다르게 적힌다 — 새마을금고는 "부산", 저축은행중앙회는
# "부산광역시"다. 안 맞추면 부산진구가 두 줄로 갈라진다 (2026-08-05 실측:
# 구 17개·시도 2개로 보이던 것이 맞춘 뒤 16개·1개가 됐다).
SIDO_ALIASES = {
    "서울특별시": "서울",
    "서울시": "서울",
    "부산광역시": "부산",
    "부산시": "부산",
    "대구광역시": "대구",
    "대구시": "대구",
    "인천광역시": "인천",
    "인천시": "인천",
    "광주광역시": "광주",
    "광주시": "광주",
    "대전광역시": "대전",
    "대전시": "대전",
    "울산광역시": "울산",
    "울산시": "울산",
    "세종특별자치시": "세종",
    "세종시": "세종",
    "경기도": "경기",
    "강원도": "강원",
    "강원특별자치도": "강원",
    "충청북도": "충북",
    "충청남도": "충남",
    "전라북도": "전북",
    "전북특별자치도": "전북",
    "전라남도": "전남",
    "경상북도": "경북",
    "경상남도": "경남",
    "제주도": "제주",
    "제주특별자치도": "제주",
}

# 부산 16개 구·군 (v4 §4.3). 화면의 구·군 필터가 이 목록을 쓴다.
#
# 데이터에서 뽑지 않고 여기 적는 이유: 수집이 덜 됐거나 한 구에 점포가
# 없으면 그 구가 화면에서 통째로 사라진다. 없는 것과 0건은 다르다.
BUSAN_DISTRICTS = (
    "강서구",
    "금정구",
    "기장군",
    "남구",
    "동구",
    "동래구",
    "부산진구",
    "북구",
    "사상구",
    "사하구",
    "서구",
    "수영구",
    "연제구",
    "영도구",
    "중구",
    "해운대구",
)

# 주소 두 번째 토막이 어떤 행정단위여야 하는지 시도 종류별로 제한한다.
#
# 전체 시·군·구 이름을 코드에 복제하지 않는 이유는 행정구역 개편 때문이다.
# 2026-07-01 전남광주통합특별시처럼 새 광역단위가 생겼는데, 정적 전국 목록을
# 두 벌로 가지면 한쪽이 곧 낡는다. 대신 이미 제품 계약으로 고정된 부산 16개는
# 위 master로 exact 검증하고, 나머지 **알려진 시도**는 주소 구조상 가능한
# 접미사만 받는다. 별칭표가 아직 모르는 새 시도는 아래 SIGUNGU_SUFFIXES로
# 보수적으로 받아 forward compatibility를 유지한다.
SIGUNGU_SUFFIXES_BY_SIDO: dict[str, tuple[str, ...]] = {
    "서울": ("구",),
    "부산": ("구", "군"),
    "대구": ("구", "군"),
    "인천": ("구", "군"),
    "광주": ("구",),
    "대전": ("구",),
    "울산": ("구", "군"),
    # 세종은 시·군·구를 한 단계 더 두지 않는다. 두 번째 토막은 도로명이다.
    "세종": (),
    "경기": ("시", "군"),
    "강원": ("시", "군"),
    "충북": ("시", "군"),
    "충남": ("시", "군"),
    "전북": ("시", "군"),
    "전남": ("시", "군"),
    "경북": ("시", "군"),
    "경남": ("시", "군"),
    "제주": ("시",),
}
SIGUNGU_SUFFIXES = ("시", "군", "구")

# 원천별 지역 근거. **정찰로 확인된 것만 적는다** (v4 §0.2).
#
# nh_local은 2026-08-06 정찰로 확정했다. 명부의 주소가 조합이 아니라
# **점포마다 다르다** — 대저농협 하나가 맥도지점(공항로393번길)·공항지점
# (공항로811번길)·평강지점(낙동북로188번길)을 서로 다른 주소로 싣는다.
# 부산 120개 점포 중 지점이 둘 이상인 조합 16개가 전부 그랬다.
SOURCE_GEO_BASIS = {
    "kfcc": GeoBasis.OUTLET_ADDRESS,
    "cu": GeoBasis.SOURCE_QUERY_REGION,
    "fsb": GeoBasis.HEAD_OFFICE,
    # finlife는 권역마다 소스가 갈린다 (v4 §6.2). 둘 다 전국 공시라
    # geo_basis는 같지만, 이름이 없으면 지역이 통째로 비어 버린다.
    "finlife_savings_bank": GeoBasis.NATIONWIDE,
    "finlife_bank": GeoBasis.NATIONWIDE,
    # 옛 이름. 마이그레이션 전에 만들어진 행이 아직 이 값을 갖고 있을 수 있다.
    "finlife": GeoBasis.NATIONWIDE,
    "nh_local": GeoBasis.OUTLET_ADDRESS,
}

# 구·군까지 좁힐 수 있는 근거. 나머지는 시도까지만 말할 수 있다.
DISTRICT_CAPABLE = frozenset({GeoBasis.OUTLET_ADDRESS, GeoBasis.INSTITUTION_ADDRESS})

# 아는 시도 이름. 위 별칭표가 내놓는 값들이 전부다.
KNOWN_SIDO = frozenset(SIDO_ALIASES.values())

# 시도 이름이 끝나는 말. 별칭표에 없는 이름이라도 이걸로 끝나면 시도로 본다.
#
# 별칭표를 늘리는 것만으로는 부족하다. 행정구역은 바뀐다 — 강원도가
# 강원특별자치도가 됐고, 실측 데이터에 `전남광주통합특별시`가 들어 있다.
# 모르는 이름을 전부 버리면 그때마다 지역이 통째로 사라진다.
#
# `시`는 일부러 뺐다. 시도 중에 그냥 `○○시`인 곳은 없다 — 전부 특별시나
# 광역시나 특별자치시다. `시`까지 받으면 `여수시`처럼 시군구가 앞으로
# 올라온 주소를 시도로 착각한다.
SIDO_SUFFIXES = ("특별시", "광역시", "특별자치시", "도")


def normalize_sido(sido: str | None) -> str | None:
    """시도 표기를 표준형으로.

    >>> normalize_sido("부산광역시"), normalize_sido("부산"), normalize_sido(None)
    ('부산', '부산', None)

    모르는 표기는 그대로 둔다. 억지로 맞추면 없는 지역이 생긴다.

    >>> normalize_sido("신동해빌딩")
    '신동해빌딩'
    """
    if sido is None:
        return None
    return SIDO_ALIASES.get(sido, sido)


def looks_like_sigungu(sido: str | None, token: str | None) -> bool:
    """주소 두 번째 토막이 그 시도의 시·군·구로 볼 수 있는가.

    부산은 화면 계약에 쓰는 16개 구·군 master와 정확히 맞춘다.

    >>> looks_like_sigungu("부산", "동구"), looks_like_sigungu("부산", "가짜구")
    (True, False)

    알려진 시도는 행정계층에 맞는 접미사만 받는다. 도로명은 여기서 탈락한다.

    >>> looks_like_sigungu("대구", "달서구"), looks_like_sigungu("대구", "동덕로")
    (True, False)
    >>> looks_like_sigungu("경기", "수원시"), looks_like_sigungu("경기", "판교로")
    (True, False)
    >>> looks_like_sigungu("세종", "도움6로")
    False

    별칭표가 아직 모르는 새 광역단위는 시·군·구 접미사까지만 요구한다.
    이름을 미리 발명하지 않으면서 실제 주소의 지역 정보는 보존한다.

    >>> looks_like_sigungu("전남광주통합특별시", "여수시")
    True
    >>> looks_like_sigungu("전남광주통합특별시", "쌍봉로")
    False
    """
    if not token or not looks_like_sido(sido):
        return False
    normalized_sido = normalize_sido(sido)
    if normalized_sido == "부산":
        return token in BUSAN_DISTRICTS
    expected = SIGUNGU_SUFFIXES_BY_SIDO.get(normalized_sido)
    if expected is not None:
        return token.endswith(expected)
    return token.endswith(SIGUNGU_SUFFIXES)


def split_address(address: str | None) -> tuple[str | None, str | None]:
    """주소에서 (시도, 시·군·구). 시도 표기는 맞춰서 돌려준다.

    주소가 유일하게 믿을 수 있는 근거다. 원천이 주는 지역 코드는 그 사이트의
    조회 구분값이지 행정구역이 아니다 — 새마을금고 `r1=광주`를 조회하면
    전남 주소 124건이 함께 온다 (2026-08-05 실측).

    >>> split_address("부산광역시 동구 중앙대로 260")
    ('부산', '동구')
    >>> split_address("부산 중구 대청로 101-1")
    ('부산', '중구')

    두 번째 토막이 도로명이면 시군구로 승격하지 않는다. 실제 오류였던
    `대구 / 동덕로`가 이 경로에서 생겼다.

    >>> split_address("대구광역시 동덕로 6")
    ('대구', None)
    >>> split_address("세종특별자치시 도움6로 42")
    ('세종', None)

    토막이 모자라면 지어내지 않고 비운다.

    >>> split_address("세종특별자치시")
    ('세종', None)
    >>> split_address(None)
    (None, None)

    주소처럼 안 생긴 값은 시도 검증에서 최종적으로 비워진다. 여기서도 두 번째
    토막을 시군구로 만들지는 않는다.

    >>> split_address("신동해빌딩 1,2,3층")
    ('신동해빌딩', None)
    """
    tokens = (address or "").split()
    if not tokens:
        return None, None
    sido = normalize_sido(tokens[0])
    if len(tokens) == 1:
        return sido, None
    sigungu = tokens[1] if looks_like_sigungu(sido, tokens[1]) else None
    return sido, sigungu


def geo_basis_for(source_id: str) -> GeoBasis:
    """그 원천의 지역이 무엇에서 왔는가.

    모르는 원천은 `none`이다. 기본값을 `outlet_address` 같은 것으로 두면
    근거 없는 값이 근거 있어 보인다.

    >>> geo_basis_for("kfcc"), geo_basis_for("fsb")
    (<GeoBasis.OUTLET_ADDRESS: 'outlet_address'>, <GeoBasis.HEAD_OFFICE: 'head_office'>)
    >>> geo_basis_for("어디도아님")
    <GeoBasis.NONE: 'none'>
    """
    return SOURCE_GEO_BASIS.get(source_id, GeoBasis.NONE)


def supports_district(basis: GeoBasis | str) -> bool:
    """구·군까지 좁혀 말할 수 있는가.

    본점 기준이나 전국 공시를 구·군으로 거르면, 사용자는 결과가 없는 것을
    "그 구에 상품이 없다"로 읽는다. 실제로는 그 원천이 구 단위를 말할 수
    없을 뿐이다 (v4 §4.3).

    >>> supports_district(GeoBasis.OUTLET_ADDRESS)
    True
    >>> supports_district(GeoBasis.HEAD_OFFICE), supports_district("nationwide")
    (False, False)
    """
    return GeoBasis(basis) in DISTRICT_CAPABLE


def region_fields(
    source_id: str, address: str | None, *, query_region: str | None = None
) -> RegionFields:
    """기관·점포 행에 넣을 지역 네 칸. 규칙은 여기 한 곳에만 있다.

    수집할 때(`entity_service`)와 옛 데이터를 채울 때(마이그레이션)가 같은
    함수를 써야 한다. 두 벌로 두면 백필한 행과 새로 들어온 행이 다른
    규칙으로 채워지고, 그 차이는 몇 달 뒤 집계가 어긋날 때까지 안 보인다.

    >>> f = region_fields("kfcc", "부산광역시 동구 중앙대로 260")
    >>> f.sido, f.sigungu, f.basis.value, f.confidence
    ('부산', '동구', 'outlet_address', 'high')

    본점 주소는 구까지 적혀 있어도 구를 말할 수 없다. 그 구에 지점이 있다는
    뜻이 아니라 본점이 거기 있다는 뜻이다 (v4 §4.3).

    >>> f = region_fields("fsb", "부산광역시 동구 중앙대로 260")
    >>> f.sigungu, f.basis.value, f.confidence
    ('동구', 'head_office', 'medium')

    주소가 없으면 지어내지 않는다.

    >>> f = region_fields("finlife", None)
    >>> f.sido, f.sigungu, f.basis.value, f.confidence
    (None, None, 'nationwide', 'none')

    주소처럼 안 생긴 값도 지역 자리에 넣지 않는다. 원문은 `address` 칸에
    남으니 잃는 것은 없다.

    >>> f = region_fields("fsb", "신동해빌딩 1,2,3층")
    >>> f.sido, f.sigungu, f.confidence
    (None, None, 'none')

    시도는 맞지만 두 번째 토막이 도로명이면 시도까지만 남긴다.

    >>> f = region_fields("fsb", "대구광역시 동덕로 6")
    >>> f.sido, f.sigungu, f.confidence
    ('대구', None, 'medium')

    별칭표가 모르는 시도는 그대로 살린다. 시군구가 붙어 있는 진짜 주소다.

    >>> f = region_fields("kfcc", "전남광주통합특별시 여수시 쌍봉로 23-2")
    >>> f.sido, f.sigungu, f.confidence
    ('전남광주통합특별시', '여수시', 'high')

    ── 조회조건에서 오는 지역 (2026-08-07) ─────────────────────────────

    신협은 주소를 아예 주지 않는다. 대신 **어느 지역으로 조회했는지**는 안다.
    그것도 지역 정보다 — "그 지역에서 영업하는 조합"이라는 뜻이다. 주소가
    아니므로 시군구는 끝까지 비우고, `geo_basis`가 근거를 밝힌다.

    >>> f = region_fields("cu", None, query_region="부산")
    >>> f.sido, f.sigungu, f.basis.value, f.confidence
    ('부산', None, 'source_query_region', 'medium')

    조회조건이 근거가 아닌 원천에는 주지 않는다. 주소를 주는 원천에 조회
    지역을 섞으면 어느 쪽이 답인지 알 수 없게 된다.

    >>> region_fields("kfcc", None, query_region="부산").sido is None
    True

    화면이 시도로 안 나누는 묶음은 그대로 살린다. 한쪽 이름을 붙이면
    나머지 지역이 거짓으로 그 지역에 들어간다 (신협 코드 18 = 광주·전남).

    >>> region_fields("cu", None, query_region="광주·전남").sido
    '광주·전남'
    """
    basis = geo_basis_for(source_id)
    if basis is GeoBasis.SOURCE_QUERY_REGION and address is None and query_region:
        return RegionFields(query_region, None, basis, "medium")
    sido, sigungu = split_address(address)
    if not looks_like_sido(sido):
        # 지역이 아니면 지역 자리에 넣지 않는다. 주소 원문은 `address` 칸에
        # 그대로 남으므로 잃는 것은 없고, 화면의 지역 필터만 깨끗해진다.
        sido, sigungu = None, None
    if sido is None:
        confidence = "none"
    elif sigungu is not None and supports_district(basis):
        confidence = "high"
    else:
        confidence = "medium"
    return RegionFields(sido, sigungu, basis, confidence)


def is_known_sido(sido: str | None) -> bool:
    """별칭표가 아는 이름인가.

    >>> is_known_sido("부산"), is_known_sido(None)
    (True, False)
    >>> is_known_sido("전남광주통합특별시")
    False
    """
    return sido in KNOWN_SIDO


def looks_like_sido(token: str | None) -> bool:
    """이 토막이 시도 이름 자리에 올 수 있는 말인가.

    별칭표에 없어도 시도처럼 끝나면 시도로 본다. 행정구역 이름은 바뀌고,
    실측에 `전남광주통합특별시`가 있다 — 여수시·구례군·서구 같은 시군구가
    멀쩡히 붙어 있는 진짜 주소다. 모르는 이름을 버리면 그 11건의 지역이
    통째로 사라진다.

    >>> looks_like_sido("부산"), looks_like_sido("전남광주통합특별시")
    (True, True)

    반대로 이건 지역이 아니다. 저축은행중앙회가 동양저축은행 주소로
    `신동해빌딩 1,2,3층`을 준다 — 시도도 구도 없는 세부 주소 조각이라
    같은 원천의 다른 기관(`부산광역시 동구 범일로 92`)과 형태가 다르다.
    이걸 시도로 두면 화면의 지역 필터에 `신동해빌딩`이, 구·군 필터에
    `1,2,3층`이 뜬다.

    >>> looks_like_sido("신동해빌딩"), looks_like_sido("1,2,3층")
    (False, False)
    >>> looks_like_sido(None)
    False
    """
    if not token:
        return False
    return token in KNOWN_SIDO or token.endswith(SIDO_SUFFIXES)


def normalize_sido_sql(column: str) -> str:
    """시도 표기를 맞추는 SQL 식.

    값은 위 표의 열쇠뿐이라 문자열을 그대로 넣어도 안전하다.

    >>> normalize_sido_sql("x")[:19]
    "CASE x WHEN '서울특별시'"
    """
    whens = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in SIDO_ALIASES.items())
    return f"CASE {column} {whens} ELSE {column} END"
