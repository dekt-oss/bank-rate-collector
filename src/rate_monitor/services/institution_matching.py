"""두 원천이 같은 저축은행을 다르게 부른다 (v4 §11.1).

같은 은행인데 이름이 다르다.

    finlife   BNK저축은행   디비저축은행   엔에이치저축은행   키움예스저축은행
    FSB       BNK           DB             NH                 키움YES

이 이름들이 안 붙으면 화면에 같은 상품이 두 줄로 나온다. 반대로 잘못 붙이면
서로 다른 은행의 금리가 하나로 합쳐진다 — 뒤쪽이 훨씬 나쁘다.

**규칙으로 되는 데까지만 하고, 나머지는 손으로 적는다.** 로마자 음차를
자동으로 풀려고 하면 "대신"과 "DS"를 붙일지 말지 같은 판단이 생기고, 그건
데이터로 답할 수 없다.
"""

import re

# 이름에서 걷어내는 말. 이것만으로 79곳 중 75곳이 붙는다 (2026-08-06 실측).
_NOISE = re.compile(r"[\s()·\-]|저축은행|상호|주식회사|㈜")

# 규칙으로 안 붙는 나머지. 전부 영문↔한글 음차다.
#
# 손으로 적는 이유: 넷뿐이고, 자동으로 풀면 "대신"↔"DS" 같은 잘못된 결합이
# 조용히 생긴다. 원천이 이름을 바꾸면 여기서 안 붙고, 안 붙은 것은
# `unmatched()`가 세어 준다.
MANUAL_ALIASES = {
    "MS": "엠에스",
    "디비": "DB",
    "엔에이치": "NH",
    "키움예스": "키움YES",
}


def normalize_institution(name: str | None) -> str:
    """기관명을 비교 가능한 형태로.

    >>> normalize_institution("BNK저축은행")
    'BNK'
    >>> normalize_institution("대명상호저축은행")
    '대명'
    >>> normalize_institution("디비저축은행") == normalize_institution("DB")
    True
    >>> normalize_institution(None)
    ''
    """
    if not name:
        return ""
    key = _NOISE.sub("", name)
    return MANUAL_ALIASES.get(key, key)


def unmatched(left: set[str], right: set[str]) -> tuple[set[str], set[str]]:
    """정규화해도 안 붙는 이름들.

    붙은 것보다 **안 붙은 것**이 중요하다. 원천이 이름을 바꾸면 조용히
    중복이 살아나므로, 그 수를 셀 수 있어야 한다.

    >>> unmatched({"BNK저축은행"}, {"BNK", "웰컴"})
    (set(), {'웰컴'})
    """
    ln = {normalize_institution(n) for n in left}
    rn = {normalize_institution(n) for n in right}
    return (
        {n for n in left if normalize_institution(n) not in rn},
        {n for n in right if normalize_institution(n) not in ln},
    )
