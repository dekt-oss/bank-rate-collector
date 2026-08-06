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

from rate_monitor.domain.enums import GeoBasis

# 시도 표기를 맞춘다.
#
# 같은 곳이 원천마다 다르게 적힌다 — 새마을금고는 "부산", 저축은행중앙회는
# "부산광역시"다. 안 맞추면 부산진구가 두 줄로 갈라진다 (2026-08-05 실측:
# 구 17개·시도 2개로 보이던 것이 맞춘 뒤 16개·1개가 됐다).
SIDO_ALIASES = {
    "서울특별시": "서울", "서울시": "서울",
    "부산광역시": "부산", "부산시": "부산",
    "대구광역시": "대구", "대구시": "대구",
    "인천광역시": "인천", "인천시": "인천",
    "광주광역시": "광주", "광주시": "광주",
    "대전광역시": "대전", "대전시": "대전",
    "울산광역시": "울산", "울산시": "울산",
    "세종특별자치시": "세종", "세종시": "세종",
    "경기도": "경기",
    "강원도": "강원", "강원특별자치도": "강원",
    "충청북도": "충북", "충청남도": "충남",
    "전라북도": "전북", "전북특별자치도": "전북",
    "전라남도": "전남",
    "경상북도": "경북", "경상남도": "경남",
    "제주도": "제주", "제주특별자치도": "제주",
}

# 부산 16개 구·군 (v4 §4.3). 화면의 구·군 필터가 이 목록을 쓴다.
#
# 데이터에서 뽑지 않고 여기 적는 이유: 수집이 덜 됐거나 한 구에 점포가
# 없으면 그 구가 화면에서 통째로 사라진다. 없는 것과 0건은 다르다.
BUSAN_DISTRICTS = (
    "강서구", "금정구", "기장군", "남구", "동구", "동래구", "부산진구", "북구",
    "사상구", "사하구", "서구", "수영구", "연제구", "영도구", "중구", "해운대구",
)

# 원천별 지역 근거. **정찰로 확인된 것만 적는다** (v4 §0.2).
#
# nh_local은 일부러 비어 있다. 수집기가 없고, 상세화면이 점포 단위인지
# 조합 단위인지 아직 모른다 — 추정해 넣으면 나중에 데이터를 다시 훑어야
# 한다. v4 PR 3 정찰 뒤에 채운다.
SOURCE_GEO_BASIS = {
    "kfcc": GeoBasis.OUTLET_ADDRESS,
    "cu": GeoBasis.SOURCE_QUERY_REGION,
    "fsb": GeoBasis.HEAD_OFFICE,
    "finlife": GeoBasis.NATIONWIDE,
}

# 구·군까지 좁힐 수 있는 근거. 나머지는 시도까지만 말할 수 있다.
DISTRICT_CAPABLE = frozenset({GeoBasis.OUTLET_ADDRESS, GeoBasis.INSTITUTION_ADDRESS})


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


def split_address(address: str | None) -> tuple[str | None, str | None]:
    """주소에서 (시도, 구·군). 시도 표기는 맞춰서 돌려준다.

    주소가 유일하게 믿을 수 있는 근거다. 원천이 주는 지역 코드는 그 사이트의
    조회 구분값이지 행정구역이 아니다 — 새마을금고 `r1=광주`를 조회하면
    전남 주소 124건이 함께 온다 (2026-08-05 실측).

    >>> split_address("부산광역시 동구 중앙대로 260")
    ('부산', '동구')
    >>> split_address("부산 중구 대청로 101-1")
    ('부산', '중구')

    토막이 모자라면 지어내지 않고 비운다.

    >>> split_address("세종특별자치시")
    ('세종', None)
    >>> split_address(None)
    (None, None)

    주소처럼 안 생긴 값도 통과시킨다. 실제로 있다 — 저축은행 본점 주소에
    `신동해빌딩 1,2,3층`이 있다. 버리면 그 기관이 사라지고, 고치면 없는
    지역을 만든다.

    >>> split_address("신동해빌딩 1,2,3층")
    ('신동해빌딩', '1,2,3층')
    """
    tokens = (address or "").split()
    if not tokens:
        return None, None
    if len(tokens) == 1:
        return normalize_sido(tokens[0]), None
    return normalize_sido(tokens[0]), tokens[1]


def geo_basis_for(source_id: str) -> GeoBasis:
    """그 원천의 지역이 무엇에서 왔는가.

    모르는 원천은 `none`이다. 기본값을 `outlet_address` 같은 것으로 두면
    근거 없는 값이 근거 있는 것처럼 보인다.

    >>> geo_basis_for("kfcc"), geo_basis_for("fsb")
    (<GeoBasis.OUTLET_ADDRESS: 'outlet_address'>, <GeoBasis.HEAD_OFFICE: 'head_office'>)
    >>> geo_basis_for("nh_local")
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


def normalize_sido_sql(column: str) -> str:
    """시도 표기를 맞추는 SQL 식.

    값은 위 표의 열쇠뿐이라 문자열을 그대로 넣어도 안전하다.

    >>> normalize_sido_sql("x")[:19]
    "CASE x WHEN '서울특별시'"
    """
    whens = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in SIDO_ALIASES.items())
    return f"CASE {column} {whens} ELSE {column} END"
