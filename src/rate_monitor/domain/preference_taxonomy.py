"""우대조건 원문을 표준 분류로 옮긴다 (우대조건 명세서 v1 §5·§7).

원문은 **언제나 그대로 보존한다.** 여기서 만드는 것은 원문을 대체하는
값이 아니라 화면에서 걸러 보기 위한 꼬리표다. 분류가 틀려도 원문은 표에
그대로 남아 있어서 사람이 확인할 수 있다.

── 세 상태를 구별한다 ─────────────────────────────────────────────

    MISSING   원천이 우대조건 칸 자체를 안 준다        109,149건  72.6%
    NONE      원천이 "없음"이라고 말한다               30,957건  20.6%
    PRESENT   조건이 적혀 있다                         10,205건   6.8%

(2026-08-06 발행 DB, 관측 150,311건 실측)

`MISSING`을 `NONE`으로 뭉개면 우대금리가 없는 상품처럼 보인다. 새마을금고는
공식 화면에 우대금리 열 자체가 없어서 전체의 69%가 여기 걸린다 — 그걸
"우대조건 없음"이라고 적으면 화면이 거짓말을 한다 (v4 §3.3).

── 한 조건이 여러 분류에 들 수 있다 ───────────────────────────────

「비대면 기한부예금 가입실적」은 비대면이면서 상품보유다. 하나로 우겨넣지
않는다. 사람이 어느 쪽으로 찾든 나와야 한다.

분류 규칙은 `config/preference_rules.yaml`에 있다. 판단이 바뀌면 코드가
아니라 그 파일을 고치고, PR이 그대로 감사기록이 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

RULES_PATH = Path("config/preference_rules.yaml")

# 규칙에 하나도 안 걸린 조건. 화면에서는 «기타»로 보인다.
OTHER = "OTHER"
OTHER_LABEL = "기타"


class PreferenceStatus(StrEnum):
    """우대조건 원문이 어떤 상태인가."""

    MISSING = "missing"   # 원천이 칸 자체를 안 준다
    NONE = "none"         # 원천이 "없음"이라고 말한다
    PRESENT = "present"   # 조건이 적혀 있다


@dataclass(frozen=True)
class PreferenceTags:
    """한 관측의 우대조건 판정."""

    status: PreferenceStatus
    codes: tuple[str, ...]


# 저축은행중앙회·신협은 여러 칸을 라벨로 이어 붙여 준다
# (`fsb/parser.preference_raw`, `cu/parser`). 그중 «우대조건:» 뒤만 본다.
# 가입대상·유의사항까지 세면 "실명의 개인"이 우대조건으로 잡힌다.
_BODY = re.compile(
    r"우대조건\s*:\s*(.*?)(?=\n(?:가입대상|가입제한|유의사항|기타)\s*:|\Z)",
    re.S,
)


@lru_cache(maxsize=4)
def _rules(path: str | None = None) -> dict[str, Any]:
    config = Path(path) if path else RULES_PATH
    if not config.exists():
        return {"categories": {}, "explicit_none": []}
    return yaml.safe_load(config.read_text(encoding="utf-8")) or {}


def labels(path: str | None = None) -> dict[str, str]:
    """분류 코드 → 화면 표시명. «기타»가 마지막에 붙는다.

    >>> labels()["CARD_USAGE"]
    '카드 이용'
    >>> labels()["OTHER"]
    '기타'
    """
    out = {
        code: (spec or {}).get("label", code)
        for code, spec in (_rules(path).get("categories") or {}).items()
    }
    out[OTHER] = OTHER_LABEL
    return out


def condition_body(raw: str) -> str:
    """라벨 붙은 원문에서 우대조건 부분만 떼어낸다.

    >>> condition_body("우대조건: 급여이체\\n가입대상: 실명의 개인")
    '급여이체'

    라벨이 없으면 원문 전체가 조건이다 (신협·농·축협이 그렇다).

    >>> condition_body("급여이체 실적 : 0.1%p")
    '급여이체 실적 : 0.1%p'
    """
    found = _BODY.search(raw)
    return (found.group(1) if found else raw).strip()


def classify(raw: str | None, path: str | None = None) -> PreferenceTags:
    """원문 한 건을 판정한다.

    원천이 아무것도 안 주면 `MISSING`이다. 빈 문자열도 마찬가지다 —
    수집기가 `preference_raw=""`로 채우는 곳이 있다 (kfcc).

    >>> classify(None).status
    <PreferenceStatus.MISSING: 'missing'>
    >>> classify("   ").status
    <PreferenceStatus.MISSING: 'missing'>

    원천이 스스로 없다고 말하면 `NONE`이고, 꼬리표는 붙이지 않는다.

    >>> classify("우대조건: 없음\\n가입대상: 제한없음").status
    <PreferenceStatus.NONE: 'none'>
    >>> classify("해당사항없음").codes
    ()

    조건이 있으면 걸리는 분류를 **모두** 붙인다.

    >>> classify("신협체크카드 결제실적 : 0.2%p").codes
    ('CARD_USAGE',)
    >>> sorted(classify("비대면 기한부예금 가입실적").codes)
    ['DIGITAL_CHANNEL', 'PRODUCT_HOLDING']

    규칙에 하나도 안 걸리면 «기타»다. 값을 지어내지 않는다.

    >>> classify("월이자지급식과 금리가 다를 수 있음").codes
    ('OTHER',)
    """
    if raw is None or not raw.strip():
        return PreferenceTags(PreferenceStatus.MISSING, ())

    body = condition_body(raw)
    rules = _rules(path)
    if not body or body in set(rules.get("explicit_none") or ()):
        return PreferenceTags(PreferenceStatus.NONE, ())

    found: list[str] = []
    for code, spec in (rules.get("categories") or {}).items():
        keywords = (spec or {}).get("keywords") or ()
        if any(word in body for word in keywords):
            found.append(code)
    return PreferenceTags(PreferenceStatus.PRESENT, tuple(found) or (OTHER,))
