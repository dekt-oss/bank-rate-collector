"""농·축협 화면을 표준 행으로 옮긴다 (v4 §5, PR 4).

계약은 `docs/source-recon/nh-local.md` §0.2에 실측으로 적혀 있다. 요약하면
GET 두 번이다.

    SFDPW0161R.view                    전국 점포 명부 4,871행 (페이지네이션 없음)
    SFDPW016{2,3,4}R.view?brc=<코드>   점포별 금리 (입출금식/거치식/적립식)

**여기서는 네트워크를 타지 않는다.** 받아 온 HTML을 넣으면 행이 나온다.
어댑터가 받아 오고, 이 파일이 읽는다 (v3 §6.2).
"""

import re
from datetime import date
from hashlib import sha256
from typing import NamedTuple

from rate_monitor.collectors.base import SchemaChangedError
from rate_monitor.collectors.kfcc.parser import parse_term
from rate_monitor.domain.enums import (
    AvailabilityScope,
    InterestMethod,
    JoinChannel,
    ProductType,
    RateScope,
    Sector,
    SourceRole,
    TrustLevel,
)
from rate_monitor.domain.normalization import parse_rate
from rate_monitor.domain.schemas import ParsedRateRow

SOURCE_ID = "nh_local"

# 상품 분류마다 화면이 다르다 (`lfViewInquiry`의 inq_dsc).
SCREEN_BY_PRODUCT = {
    ProductType.DEMAND_DEPOSIT: "SFDPW0162R",      # 입출금식
    ProductType.TERM_DEPOSIT: "SFDPW0163R",        # 거치식
    ProductType.INSTALLMENT_SAVINGS: "SFDPW0164R",  # 적립식
}

_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<td([^>]*)>(.*?)</td>", re.S | re.I)
_ROWSPAN = re.compile(r'rowspan\s*=\s*"?(\d+)', re.I)
_TAG = re.compile(r"<[^>]+>")
_INQUIRY = re.compile(r"lfViewInquiry\(\s*'([^']+)'\s*,\s*'([^']*)'")

# 명부 표를 알아보는 표식. 원천이 열을 바꾸면 여기서 걸린다.
LIST_HEADERS = ("농&middot;축협 명", "주소", "전화번호")
DETAIL_CAPTION = "금리 상세정보"


def _text(raw: str) -> str:
    """태그를 걷어내고 공백을 하나로. `<br>`은 줄바꿈 대신 공백으로 둔다."""
    return re.sub(r"\s+", " ", _TAG.sub(" ", raw)).replace("&nbsp;", " ").strip()


class NhOutlet(NamedTuple):
    """명부 한 줄.

    **전화번호는 담지 않는다.** 원천이 주지만 우리가 다룰 데이터가 아니다 —
    저축은행중앙회 `TEL`/`CTEL`, 신협 `ownTelNo`와 같은 이유다 (v3.1 §16.2).
    """

    brc: str
    name: str
    address: str


def parse_outlet_list(html: str) -> list[NhOutlet]:
    """전국 점포 명부.

    `lfViewInquiry('333072', '강릉농협 강동지점')`의 첫 인자가 점포 식별자다.
    이름은 두 번째 인자가 아니라 표의 `<span>`에서 읽는다 — 상세 요청에
    실어 보낼 값과 화면에 보일 값이 같아야 하므로 둘이 다르면 표를 믿는다.

    >>> rows = parse_outlet_list('''
    ...   <table><caption>검색 결과</caption>
    ...   <thead><tr><th>번호</th><th>농&middot;축협 명</th><th>주소</th>
    ...              <th>전화번호</th><th>조회</th></tr></thead><tbody>
    ...   <tr><td>1</td><td class="data1"><span>가락농협</span></td>
    ...       <td class="txt">부산광역시 강서구 가락대로 1459</td>
    ...       <td>051-000-0000</td>
    ...       <td><button onclick="lfViewInquiry('817020', '가락농협');return false;">
    ...           금리조회</button></td></tr>
    ...   </tbody></table>''')
    >>> rows
    [NhOutlet(brc='817020', name='가락농협', address='부산광역시 강서구 가락대로 1459')]

    전화번호 열은 읽고도 버린다.

    >>> "051" in str(rows)
    False
    """
    if not all(header in html for header in LIST_HEADERS):
        raise SchemaChangedError(f"명부 표의 머리글이 바뀌었다: {LIST_HEADERS}")

    outlets: list[NhOutlet] = []
    for block in _TR.findall(html):
        inquiry = _INQUIRY.search(block)
        if inquiry is None:
            continue  # 머리글 행
        cells = [_text(body) for _, body in _TD.findall(block)]
        if len(cells) < 3:
            continue
        # 열 순서: 번호 | 농·축협 명 | 주소 | 전화번호 | 조회
        outlets.append(NhOutlet(brc=inquiry.group(1), name=cells[1], address=cells[2]))
    return outlets


class RateEntry(NamedTuple):
    """상세표 한 줄. 화면에 보이는 그대로다."""

    product_name: str
    term_raw: str
    rate_raw: str
    note: str
    interest_note: str


def parse_rate_table(html: str) -> list[RateEntry]:
    """금리 상세표.

    상품명·비고·금리유형에 `rowspan`이 걸려 **첫 행만 그 칸을 갖는다.** 열
    인덱스를 고정하면 둘째 행부터 기간을 상품명으로 읽는다. 이어지는 칸을
    들고 내려간다.

    >>> table = '''<table><caption>금리 상세정보</caption><tbody>
    ...   <tr><td rowspan="2">정기예탁금</td><td>12개월 이상~24개월 미만</td>
    ...       <td class="data2"><strong>3%</strong></td>
    ...       <td rowspan="2">- 만기이자지급식 기준</td>
    ...       <td rowspan="2">고정금리</td></tr>
    ...   <tr><td>24개월 이상~36개월 미만</td>
    ...       <td class="data2"><strong>2.5%</strong></td></tr>
    ...   </tbody></table>'''
    >>> for e in parse_rate_table(table):
    ...     print(e.product_name, "|", e.term_raw, "|", e.rate_raw, "|", e.interest_note)
    정기예탁금 | 12개월 이상~24개월 미만 | 3% | 고정금리
    정기예탁금 | 24개월 이상~36개월 미만 | 2.5% | 고정금리
    """
    if DETAIL_CAPTION not in html:
        raise SchemaChangedError(f"상세표 캡션 {DETAIL_CAPTION!r}이 없다")

    entries: list[RateEntry] = []
    # rowspan으로 이어지는 칸. 남은 줄 수를 함께 들고 있어야 다음 상품에서
    # 옛 값이 새어 나오지 않는다.
    carried: dict[str, tuple[str, int]] = {}

    for block in _TR.findall(html):
        cells = [(attrs, _text(body)) for attrs, body in _TD.findall(block)]
        if not cells:
            continue

        if len(cells) >= 5:
            # 상품이 시작하는 줄. 다섯 칸이 다 있다.
            product, term, rate, note, interest = (value for _, value in cells[:5])
            span = _ROWSPAN.search(cells[0][0])
            remaining = (int(span.group(1)) if span else 1) - 1
            if remaining > 0:
                carried = {
                    "product": (product, remaining),
                    "note": (note, remaining),
                    "interest": (interest, remaining),
                }
            else:
                carried = {}
        elif len(cells) == 2 and carried:
            # 이어지는 줄. 기간과 금리만 있다.
            term, rate = cells[0][1], cells[1][1]
            product = carried["product"][0]
            note = carried["note"][0]
            interest = carried["interest"][0]
            carried = {
                key: (value, left - 1) for key, (value, left) in carried.items() if left > 1
            }
        else:
            continue

        if not term or not rate:
            continue
        entries.append(RateEntry(product, term, rate, note, interest))

    return entries


def _interest_method(note: str) -> str:
    """복리인지 단리인지. 상품명과 비고가 말해 준다.

    >>> _interest_method("복리식정기예탁금 이자를 월복리로")
    'compound'
    >>> _interest_method("만기이자지급식 기준")
    'simple'
    """
    return InterestMethod.COMPOUND.value if "복리" in note else InterestMethod.SIMPLE.value


def _join_channel(product_name: str) -> str:
    """가입 채널. 상품명이 밝히는 것만 받는다.

    >>> _join_channel("e-joy 인터넷예금 우대금리"), _join_channel("정기예탁금")
    ('internet', 'unknown')
    """
    if "인터넷" in product_name or "e-joy" in product_name:
        return JoinChannel.INTERNET.value
    return JoinChannel.UNKNOWN.value


def parse_detail(
    html: str,
    *,
    outlet: NhOutlet,
    product_type: ProductType,
    as_of: date,
) -> tuple[list[ParsedRateRow], list[str]]:
    """상세 화면 → 표준 행.

    `as_of`는 조회일이다. 이 원천은 별도 공시일을 주지 않는다 —
    화면에 찍히는 날짜가 곧 요청한 날짜다 (정찰 §0.2).
    """
    rows: list[ParsedRateRow] = []
    warnings: list[str] = []

    for index, entry in enumerate(parse_rate_table(html)):
        term_months, term_days, term_error = parse_term(entry.term_raw)
        rate = parse_rate(entry.rate_raw)

        status, message = "valid", None
        if rate is None:
            status, message = "error", f"금리를 읽지 못했다: {entry.rate_raw!r}"
        elif term_error:
            status, message = "warning", term_error

        if "우대금리" in entry.product_name:
            # 버리지 않는다. 원천이 공시하는 값이고, 우리가 고를 일이 아니다.
            # 다만 이것은 **더해 주는 금리**이지 그 자체로 가입할 수 있는
            # 상품이 아니다 — 비고에 "상품별 금리 + 우대금리 적용"이라고
            # 적혀 있다. 화면이 구분해 보일 수 있게 경고로 세어 둔다.
            warnings.append(f"우대금리 행: {entry.product_name} ({entry.rate_raw})")

        locator = f"{outlet.brc}/{SCREEN_BY_PRODUCT[product_type]}/{index}"
        rows.append(
            ParsedRateRow(
                source_id=SOURCE_ID,
                source_role=SourceRole.SECONDARY_OFFICIAL,
                trust_level=TrustLevel.OFFICIAL_DIRECT,
                sector=Sector.NH_LOCAL,
                source_institution_key=outlet.brc,
                source_outlet_key=outlet.brc,
                source_product_key=entry.product_name,
                institution_name=outlet.name,
                outlet_name=outlet.name,
                institution_type=None,
                # 지역은 저장 계층이 주소에서 뽑는다 (region_service). 여기서
                # 또 자르면 규칙이 두 벌이 된다 (v4 §4).
                sido=None,
                sigungu=None,
                address=outlet.address,
                product_type=product_type.value,
                product_name=entry.product_name,
                term_months=term_months,
                term_days=term_days,
                join_channel=_join_channel(entry.product_name),
                interest_method=_interest_method(
                    f"{entry.product_name} {entry.note} {entry.interest_note}"
                ),
                payment_method=None,
                amount_min=None,
                amount_max=None,
                customer_scope=None,
                # 지역 조합이라 아무나 가입할 수 있는 것이 아니다. 다만 그
                # 조건을 원천이 밝히지 않으므로 단정하지 않는다.
                availability_scope=AvailabilityScope.UNKNOWN,
                # 금리가 점포 단위로 나온다. 조합마다 다르고 지점마다 다르다.
                rate_scope=RateScope.OUTLET,
                base_rate=rate,
                # **최고 우대금리 열이 없다.** base_rate로 메우지 않는다
                # (v4 §3.3).
                max_rate=None,
                preference_raw=entry.note,
                source_row_ref=locator,
                base_source_locator=locator,
                source_record_hash=sha256(
                    "|".join(
                        (outlet.brc, entry.product_name, entry.term_raw, entry.rate_raw)
                    ).encode()
                ).hexdigest(),
                source_effective_at=as_of,
                validation_status=status,
                validation_message=message,
                extra={"note": entry.note, "interest_note": entry.interest_note},
            )
        )

    return rows, warnings


def schema_fingerprint(html: str) -> str:
    """표 모양의 지문. 원천이 열을 바꾸면 값이 달라진다 (v3.1 §7)."""
    headers = re.findall(r"<th[^>]*>(.*?)</th>", html, re.S | re.I)
    return sha256("|".join(_text(h) for h in headers).encode()).hexdigest()[:16]


BUSAN_PREFIXES = ("부산광역시", "부산 ")


def outlets_in(
    outlets: list[NhOutlet], prefixes: tuple[str, ...] | None
) -> list[NhOutlet]:
    """주소 접두어로 수집 범위를 거른다.

    원천이 지역 요청 인자를 주지 않아 명부가 통째로 온다. 범위는 받아 온
    뒤에 주소로 정한다 (정찰 §0.2).

    **이름이 아니라 주소가 근거다.** 기관명에 '부산'이 들어가도 주소가
    경남인 점포가 있다 (v4 §4.3).

    >>> rows = [NhOutlet("1", "가락농협", "부산광역시 강서구 가락대로 1459"),
    ...         NhOutlet("2", "부산경남양돈농협", "경상남도 김해시 주촌면")]
    >>> outlets_in(rows, ("부산광역시", "부산 "))
    [NhOutlet(brc='1', name='가락농협', address='부산광역시 강서구 가락대로 1459')]

    `None`은 전국이다. 빈 목록과 다르다 — 빈 목록은 아무것도 안 남는다.

    >>> len(outlets_in(rows, None)), len(outlets_in(rows, ()))
    (2, 0)
    """
    if prefixes is None:
        return list(outlets)
    return [o for o in outlets if o.address.startswith(tuple(prefixes))]


def busan_outlets(outlets: list[NhOutlet]) -> list[NhOutlet]:
    """부산 점포만. 세로절단의 모집단이다 (v4 §5.3).

    >>> busan_outlets([
    ...     NhOutlet("1", "가락농협", "부산광역시 강서구 가락대로 1459"),
    ...     NhOutlet("2", "부산경남양돈농협", "경상남도 김해시 주촌면"),
    ... ])
    [NhOutlet(brc='1', name='가락농협', address='부산광역시 강서구 가락대로 1459')]
    """
    return outlets_in(outlets, BUSAN_PREFIXES)
