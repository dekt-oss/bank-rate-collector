"""수집기 공통 예외와 마스킹 유틸.

예외 5종은 명세서 v3 §6.4를 그대로 승계한다.
"""

import re

AUTH_KEY_PATTERN = re.compile(r"(auth=)[^&\s\"']+", re.IGNORECASE)
REDACTED = "[REDACTED]"


class CollectorError(Exception):
    """수집기 계열 예외의 뿌리."""


class SourceBlockedError(CollectorError):
    """차단·캡차·접근통제. 우회하지 않고 즉시 중단한다."""


class SchemaChangedError(CollectorError):
    """원천 구조가 breaking 수준으로 바뀌었다 (v3.1 §8).

    호환 가능한 변경(선택 필드 추가 등)에는 이 예외를 쓰지 않는다.
    """


class ParseError(CollectorError):
    """공시 파일·응답 구조가 예상과 다를 때. message에 어긋난 지점을 명시한다."""


class ValidationError(CollectorError):
    """검증 규칙 위반."""


def mask_auth(text: str) -> str:
    """인증키를 마스킹한다 (v3.1 §7.4).

    request_meta, 로그, fixture 어디에도 인증키를 남기지 않는다.

    >>> mask_auth("http://x/api.json?auth=abc123&pageNo=1")
    'http://x/api.json?auth=[REDACTED]&pageNo=1'
    """
    return AUTH_KEY_PATTERN.sub(lambda m: m.group(1) + REDACTED, text)


def mask_auth_in_meta(meta: dict) -> dict:
    """요청 메타의 문자열 값과 auth 키를 재귀적으로 마스킹한다."""
    out: dict = {}
    for key, value in meta.items():
        if key.lower() == "auth":
            out[key] = REDACTED
        elif isinstance(value, str):
            out[key] = mask_auth(value)
        elif isinstance(value, dict):
            out[key] = mask_auth_in_meta(value)
        else:
            out[key] = value
    return out
