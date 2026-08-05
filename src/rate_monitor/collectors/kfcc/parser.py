"""새마을금고 공식 페이지 파서.

순수 함수다. 네트워크·파일·DB를 건드리지 않는다 (명세서 v3 §6.2).

두 종류의 문서를 다룬다. 구조는 `docs/source-recon/kfcc.md`의 실측 기록을
그대로 따른다.

    목록  GET /map/list.do?r1=&r2=
          행마다 숨김 <span title="..."> 16종. 초기 HTML에 그대로 있다.

    금리  GET /map/goods_19.do?OPEN_TRMID={gmgoCd}&gubuncode={13|14}
          divTmp1=기본이율 / divTmp2=중도해지 / divTmp4=만기후

이 경로는 공식 API 계약이 아니라 공개 웹페이지의 현재 구현 세부사항이다.
구조 지문이 바뀌면 `schema_changed`로 처리한다.
"""

import re
from datetime import date, datetime
from hashlib import sha256
from html import unescape
from typing import Any

from rate_monitor.collectors.base import SchemaChangedError
from rate_monitor.domain.enums import (
    AvailabilityScope,
    InterestMethod,
    JoinChannel,
    ProductType,
    RateScope,
    Sector,
    SourceRole,
    TrustLevel,
    ValidationStatus,
)
from rate_monitor.domain.normalization import parse_rate
from rate_monitor.domain.schemas import ParsedRateRow

SOURCE_ID = "kfcc"

# gubuncode → 상품군. 화면 h3가 스스로 붙인 이름이지 우리가 지은 게 아니다.
GROUP_PRODUCT_TYPE = {
    "13": ProductType.TERM_DEPOSIT,  # 거치식예탁금
    "14": ProductType.INSTALLMENT_SAVINGS,  # 적립식예탁금
}
GROUP_LABEL = {"12": "요구불예탁금", "13": "거치식예탁금", "14": "적립식예탁금"}

# 화면이 스스로 밝힌 성격 (docs/source-recon/kfcc.md §2.2)
#   "아래 금리는 창구판매 기준 자료로 …"
BRANCH_NOTICE = "창구판매 기준"

_TAG = re.compile(r"<[^>]+>")
_SPAN = re.compile(r'<span[^>]*title="([a-zA-Z_0-9]+)"[^>]*>([^<]*)</span>')
_DIV_TMP = re.compile(r'<div[^>]*id="(divTmp\d+)"[^>]*>')
_TBL_TIT = re.compile(r'<div class="tbl-tit">(.*?)</div>', re.S)
_TABLE = re.compile(r"<table.*?</table>", re.S)
_TH = re.compile(r"<th[^>]*>(.*?)</th>", re.S)
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD = re.compile(r"<td([^>]*)>(.*?)</td>", re.S)
_ROWSPAN = re.compile(r'rowspan="(\d+)"')
_BASIS = re.compile(r"조회기준일\s*\(([0-9]{4})[./-]([0-9]{2})[./-]([0-9]{2})\)")

# "1개월 이상", "12개월", "3년" 등 서술형 계약기간
_TERM_MONTH = re.compile(r"(\d+)\s*개월")
_TERM_YEAR = re.compile(r"(\d+)\s*년")
_TERM_DAY = re.compile(r"(\d+)\s*일")


def _text(raw: str) -> str:
    return " ".join(unescape(_TAG.sub(" ", raw)).split())


def _digest(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


# ── 목록 ────────────────────────────────────────────────────────────────


def parse_list(html: str) -> list[dict[str, str]]:
    """목록 행을 숨김 span에서 복원한다.

    같은 title이 다시 나오면 새 행이 시작된 것으로 본다.

    >>> rows = parse_list(
    ...     '<span title="gmgoCd">1</span><span title="gmgoNm">가</span>'
    ...     '<span title="gmgoCd">2</span><span title="gmgoNm">나</span>'
    ... )
    >>> [r["gmgoNm"] for r in rows]
    ['가', '나']
    """
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for title, value in _SPAN.findall(html):
        if title in current:
            rows.append(current)
            current = {}
        current[title] = value.strip()
    if current:
        rows.append(current)
    return [r for r in rows if r.get("gmgoCd")]


def check_list_schema(html: str) -> list[str]:
    """목록 구조 검사. 필수 원천키가 사라지면 breaking이다."""
    rows = parse_list(html)
    if not rows:
        raise SchemaChangedError("목록에서 gmgoCd 숨김 span을 찾지 못했다")
    warnings: list[str] = []
    required = ("gmgoCd", "divCd", "gmgoNm", "addr")
    missing = [k for k in required if k not in rows[0]]
    if missing:
        raise SchemaChangedError(f"목록 행에 필수 필드가 없다: {missing}")
    for optional in ("gmgoType", "divNm", "r1", "r2"):
        if optional not in rows[0]:
            warnings.append(f"목록 행에 {optional}가 없다. 값 없이 진행한다")
    return warnings


# ── 금리 ────────────────────────────────────────────────────────────────


def parse_term(raw: str) -> tuple[int | None, int | None, str | None]:
    """계약기간 서술형을 개월·일로 바꾼다.

    `"1개월 이상"`처럼 하한만 적힌 형태가 대부분이다. 하한을 기간으로 쓴다.
    참고 저장소는 이 형태를 파싱하지 못해 `duration: null`로 흘렸다.

    >>> parse_term("12개월 이상")
    (12, None, None)
    >>> parse_term("3년")
    (36, None, None)
    >>> parse_term("30일")
    (None, 30, None)

    읽지 못하면 값을 지어내지 않고 사유를 돌려준다.

    >>> parse_term("별도 문의")
    (None, None, "계약기간을 읽지 못했다: '별도 문의'")
    """
    text = _text(raw)
    month = _TERM_MONTH.search(text)
    if month:
        return int(month.group(1)), None, None
    year = _TERM_YEAR.search(text)
    if year:
        return int(year.group(1)) * 12, None, None
    day = _TERM_DAY.search(text)
    if day:
        return None, int(day.group(1)), None
    return None, None, f"계약기간을 읽지 못했다: {text!r}"


def parse_basis_date(html: str) -> date | None:
    """`조회기준일(2026/08/05)`에서 기준일을 뽑는다.

    없으면 None이다. `collected_at`으로 대체하지 않는다 (v3.1 §7.3).
    """
    found = _BASIS.search(html)
    if not found:
        return None
    try:
        return datetime.strptime("".join(found.groups()), "%Y%m%d").date()
    except ValueError:
        return None


def _cells(tr: str) -> list[tuple[str, int]]:
    """행의 셀을 (텍스트, rowspan)으로 돌려준다."""
    out: list[tuple[str, int]] = []
    for attrs, body in _TD.findall(tr):
        span = _ROWSPAN.search(attrs)
        out.append((_text(body), int(span.group(1)) if span else 1))
    return out


def _cell_at(cells: list[tuple[str, int]], header_index: int, offset: int) -> str | None:
    """헤더 기준 열 번호를 실제 셀 위치로 옮겨 읽는다.

    `rowspan`으로 앞쪽 셀이 빠진 행은 `offset`만큼 왼쪽으로 밀린다.
    """
    pos = header_index - offset
    return cells[pos][0] if 0 <= pos < len(cells) else None


def _rate_columns(headers: list[str]) -> list[tuple[int, str]]:
    """기본이율 열의 (위치, 지급방식)을 돌려준다.

    열 배치가 하나가 아니다. 위치로 고정하면 열이 늘 때 조용히 어긋난다.

    >>> _rate_columns(["상품명", "계약기간", "기본이율"])
    [(2, '')]
    >>> _rate_columns(["상품명", "계약기간", "월지급식 기본이율", "만기지급식 기본이율"])
    [(2, '월지급식'), (3, '만기지급식')]
    """
    out: list[tuple[int, str]] = []
    for idx, header in enumerate(headers):
        if "기본이율" not in header:
            continue
        method = header.replace("기본이율", "").strip()
        out.append((idx, method))
    return out


def _is_base_rate_table(headers: list[str]) -> bool:
    """기본이율 표인지 헤더로 판정한다.

    중도해지이율·만기후이율 표도 같은 상품명(`.tbl-tit`)을 달고 나오므로
    순서나 위치로 고르면 중도해지이율을 기본금리로 저장하게 된다.
    """
    joined = " ".join(headers)
    if "중도해지이율" in joined or "만기후이율" in joined:
        return False
    return "상품명" in joined and "기본이율" in joined


def _sections(html: str) -> list[tuple[str, str]]:
    """`divTmp1` 컨테이너를 (상품명, 표 HTML)으로 자른다.

    `divTmp1`만 믿지 않는다. 요구불 화면에는 컨테이너가 없고, 이름은 화면
    구현 세부사항이라 언제든 바뀐다. 컨테이너가 없으면 `.tbl-tit`과 뒤따르는
    표 쌍으로 되돌아간다. 어느 쪽이든 최종 판정은 헤더가 한다.
    """
    marks = list(_DIV_TMP.finditer(html))
    sections: list[tuple[str, str]] = []
    if marks:
        bounds = [m.start() for m in marks] + [len(html)]
        for i, mark in enumerate(marks):
            if mark.group(1) != "divTmp1":
                continue
            segment = html[mark.start() : bounds[i + 1]]
            title = _TBL_TIT.search(segment)
            table = _TABLE.search(segment)
            if table:
                sections.append((_text(title.group(1)) if title else "", table.group(0)))
        if sections:
            return sections

    # 되돌아가기: 상품명 div와 그 뒤 첫 표를 짝짓는다.
    for tit in _TBL_TIT.finditer(html):
        table = _TABLE.search(html, tit.end())
        if table:
            sections.append((_text(tit.group(1)), table.group(0)))
    return sections


def check_rate_schema(html: str) -> list[str]:
    """금리 페이지 구조 검사."""
    if not _TBL_TIT.search(html):
        raise SchemaChangedError("금리 페이지에 .tbl-tit 상품 제목이 없다")
    sections = _sections(html)
    if not sections:
        raise SchemaChangedError("금리 페이지에서 상품 영역을 찾지 못했다")
    warnings: list[str] = []
    if not _DIV_TMP.search(html):
        warnings.append("divTmp 컨테이너가 없다. .tbl-tit 기준으로 되돌아간다")
    if not any(
        _is_base_rate_table([_text(h) for h in _TH.findall(table)])
        for _, table in sections
    ):
        raise SchemaChangedError("기본이율 표를 하나도 찾지 못했다")
    return warnings


def schema_fingerprint(html: str) -> str:
    """구조 지문. 값이 아니라 구조가 바뀌었는지만 본다."""
    sections = _sections(html)
    shape = [
        "|".join(_text(h) for h in _TH.findall(table)) for _, table in sections
    ]
    containers = sorted({m.group(1) for m in _DIV_TMP.finditer(html)})
    return _digest(";".join(sorted(shape)) + "#" + ",".join(containers))


def parse_rates(
    html: str,
    *,
    gubuncode: str,
    outlet: dict[str, str],
    join_channel: str = JoinChannel.UNKNOWN,
) -> tuple[list[ParsedRateRow], list[str]]:
    """금리 페이지 한 장을 표준 행으로 바꾼다.

    `outlet`은 목록에서 얻은 그 금고의 대표 행이다. 금리 페이지에는 금고
    이름과 주소가 없으므로 목록 쪽 값을 붙여야 한다.

    `join_channel`은 호출자가 준다. "창구판매 기준" 안내는 이 페이지가 아니라
    이 페이지를 감싸는 `view.do`에 있어서, 금리 페이지만 보고는 알 수 없다.
    페이지 안에 문구가 있으면 그쪽을 우선한다.
    """
    warnings = check_rate_schema(html)
    basis = parse_basis_date(html)
    product_type = GROUP_PRODUCT_TYPE.get(gubuncode, ProductType.OTHER)
    gmgo_cd = outlet.get("gmgoCd", "")

    channel = JoinChannel.BRANCH if BRANCH_NOTICE in html else join_channel

    scope = (
        AvailabilityScope.WORKPLACE_MEMBERS
        if outlet.get("gmgoType") == "직장"
        else AvailabilityScope.LOCAL_MEMBERS
    )

    rows: list[ParsedRateRow] = []
    for table_idx, (title, table) in enumerate(_sections(html)):
        headers = [_text(h) for h in _TH.findall(table)]
        if not _is_base_rate_table(headers):
            continue
        rate_cols = _rate_columns(headers)
        if not rate_cols:
            warnings.append(f"기본이율 열을 찾지 못했다: {title!r} {headers}")
            continue
        try:
            term_col = next(i for i, h in enumerate(headers) if "계약기간" in h)
        except StopIteration:
            warnings.append(f"계약기간 열이 없다: {title!r} {headers}")
            continue

        rows.extend(
            _rows_from_table(
                table=table,
                table_idx=table_idx,
                title=title,
                headers=headers,
                term_col=term_col,
                rate_cols=rate_cols,
                gmgo_cd=gmgo_cd,
                outlet=outlet,
                product_type=product_type,
                basis=basis,
                channel=channel,
                scope=scope,
                gubuncode=gubuncode,
            )
        )
    return rows, warnings


def _rows_from_table(  # noqa: PLR0913 — 표 한 장을 옮기는 데 필요한 맥락이다
    *,
    table: str,
    table_idx: int,
    title: str,
    headers: list[str],
    term_col: int,
    rate_cols: list[tuple[int, str]],
    gmgo_cd: str,
    outlet: dict[str, str],
    product_type: str,
    basis: date | None,
    channel: str,
    scope: str,
    gubuncode: str,
) -> list[ParsedRateRow]:
    """표 한 장의 데이터 행을 옮긴다.

    상품명 셀에 `rowspan`이 걸려 **첫 행만 상품명 칸을 갖는다.** 열 인덱스를
    고정하면 둘째 행부터 계약기간을 상품명으로 읽는다. 앞쪽에서 비는 칸 수를
    세어 보정한다.
    """
    rows: list[ParsedRateRow] = []
    carried = 0  # 위 행에서 rowspan으로 이어지는 앞쪽 셀 수

    for tr_idx, tr in enumerate(_TR.findall(table)[1:], start=1):
        cells = _cells(tr)
        if not cells:
            continue
        offset = len(headers) - len(cells)
        if offset < 0:
            continue
        if carried > 0:
            carried -= 1
        else:
            carried = max((span for _, span in cells), default=1) - 1

        term_raw = _cell_at(cells, term_col, offset)
        if term_raw is None:
            continue
        term_months, term_days, term_error = parse_term(term_raw)

        for rate_col, method in rate_cols:
            rate_raw = _cell_at(cells, rate_col, offset)
            if rate_raw is None:
                continue
            base_rate = parse_rate(rate_raw)

            message = term_error
            status = ValidationStatus.VALID
            if term_error:
                status = ValidationStatus.ERROR
            if base_rate is None:
                status = ValidationStatus.ERROR
                message = f"금리를 읽지 못했다: {rate_raw!r}"

            locator = f"table[{table_idx}]/tr[{tr_idx}]/td[{rate_col}]"
            rows.append(
                ParsedRateRow(
                    source_id=SOURCE_ID,
                    source_role=SourceRole.PRIMARY_OFFICIAL,
                    trust_level=TrustLevel.OFFICIAL_DIRECT,
                    sector=Sector.KFCC,
                    source_institution_key=gmgo_cd,
                    # 금리는 gmgoCd 단위다. 점포마다 복제하지 않는다 (v3 §7.3.4).
                    source_outlet_key=None,
                    source_product_key=None,
                    institution_name=outlet.get("gmgoNm") or outlet.get("name") or "",
                    outlet_name=None,
                    institution_type=outlet.get("gmgoType"),
                    sido=outlet.get("r1"),
                    sigungu=outlet.get("r2"),
                    address=outlet.get("addr"),
                    product_type=product_type,
                    product_name=title,
                    term_months=term_months,
                    term_days=term_days,
                    join_channel=channel,
                    interest_method=InterestMethod.UNKNOWN,
                    payment_method=method or None,
                    amount_min=None,
                    amount_max=None,
                    customer_scope=None,
                    availability_scope=scope,
                    # 금고 단위 공시다. 점포별 적용금리가 아니다.
                    rate_scope=RateScope.INSTITUTION,
                    base_rate=base_rate,
                    # 공식 화면에 우대금리 열이 없다. base_rate로 메우지 않는다.
                    max_rate=None,
                    preference_raw="",
                    source_row_ref=f"{gmgo_cd}/{gubuncode}/{title}/{_text(term_raw)}",
                    base_source_locator=locator,
                    source_record_hash=_digest(
                        f"{gmgo_cd}|{gubuncode}|{title}|{term_raw}|{method}|{rate_raw}"
                    ),
                    source_effective_at=basis,
                    validation_status=status,
                    validation_message=message,
                    extra={
                        "gubuncode": gubuncode,
                        "group_label": GROUP_LABEL.get(gubuncode, ""),
                        "term_raw": _text(term_raw),
                        "rate_raw": _text(rate_raw),
                        "rate_column_header": headers[rate_col],
                    },
                )
            )
    return rows


def summarize(html: str) -> dict[str, Any]:
    """관측 요약. 테스트와 정찰 보고에 쓴다."""
    sections = _sections(html)
    base_tables = [
        (title, table)
        for title, table in sections
        if _is_base_rate_table([_text(h) for h in _TH.findall(table)])
    ]
    return {
        "sections": len(sections),
        "base_rate_tables": len(base_tables),
        "products": sorted({title for title, _ in base_tables}),
        "basis_date": parse_basis_date(html),
    }
