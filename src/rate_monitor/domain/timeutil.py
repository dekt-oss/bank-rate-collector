"""시간은 한국시간으로 보여 준다.

이 저장소가 다루는 것은 한국 금융기관의 공시금리이고, 읽는 사람도 한국에
있다. 화면에 `2026-08-06 05:20 UTC`라고 적혀 있으면 그날 오후 2시 20분에
수집됐다는 뜻인데, 아무도 그렇게 읽지 않는다.

**저장은 UTC로, 표시는 KST로 한다.** 저장까지 KST로 바꾸지 않는 이유는
`collection_runs.started_at`에 이미 UTC로 적힌 행이 쌓여 있기 때문이다.
지금부터 KST를 넣기 시작하면 같은 칸에 두 기준이 섞이고, 그 표는 두 값을
구별할 방법이 없다 — 시간대 정보가 없는 naive datetime이라서다.

그래서 경계에서만 바꾼다. DB에서 읽어 화면·파일로 나가는 자리에서 +9시간을
더하고, 라벨을 KST로 적는다.
"""

from datetime import UTC, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")


def now_kst() -> datetime:
    """지금, 한국시간. 시간대 정보를 달고 나온다.

    >>> now_kst().utcoffset()
    datetime.timedelta(seconds=32400)
    """
    return datetime.now(KST)


def to_kst(value: datetime | str | None) -> datetime | None:
    """UTC 시각을 한국시간으로. 시간대가 없으면 UTC로 본다.

    DB의 값은 naive UTC다. 그 사실을 여기 한 곳에만 적어 둔다.

    >>> to_kst("2026-08-06 05:20:52").isoformat()
    '2026-08-06T14:20:52+09:00'
    >>> to_kst("2026-08-06T05:20:52+00:00").isoformat()
    '2026-08-06T14:20:52+09:00'

    못 읽는 값은 지어내지 않고 비운다.

    >>> to_kst(None) is None, to_kst("") is None, to_kst("어제") is None
    (True, True, True)
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(KST)


def kst_iso(value: datetime | str | None = None) -> str | None:
    """한국시간 ISO 문자열. `+09:00`이 붙으므로 읽는 쪽이 헷갈리지 않는다.

    >>> kst_iso("2026-08-06 05:20:52")
    '2026-08-06T14:20:52+09:00'

    못 읽는 값은 원래 값을 그대로 돌려준다. 화면에서 칸이 비는 것보다
    원문이 보이는 편이 고칠 때 낫다.

    >>> kst_iso("어제")
    '어제'
    >>> kst_iso(None) is None
    True
    """
    if value is None:
        return None
    moment = to_kst(value)
    if moment is None:
        return value if isinstance(value, str) else None
    return moment.isoformat()


def kst_date_stamp(value: datetime | None = None) -> str:
    """파일 이름에 쓰는 `YYYYMMDD`, 한국 날짜 기준.

    정기 수집이 22:00 UTC에 도는데 그때 한국은 이미 다음 날 07:00이다.
    UTC로 이름을 붙이면 내려받은 파일이 하루 전 날짜를 달고 나온다.

    >>> from datetime import UTC, datetime
    >>> kst_date_stamp(datetime(2026, 8, 5, 22, 0, tzinfo=UTC))
    '20260806'
    """
    moment = to_kst(value) if value is not None else now_kst()
    assert moment is not None
    return moment.strftime("%Y%m%d")


def kst_path_stamp(value: datetime | None = None) -> str:
    """원본을 쌓는 `YYYY/MM/DD` 디렉터리, 한국 날짜 기준.

    >>> from datetime import UTC, datetime
    >>> kst_path_stamp(datetime(2026, 8, 5, 22, 0, tzinfo=UTC))
    '2026/08/06'
    """
    moment = to_kst(value) if value is not None else now_kst()
    assert moment is not None
    return moment.strftime("%Y/%m/%d")
