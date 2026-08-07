"""원천이 같은 응답을 되풀이하고 있는지 지켜본다.

── 왜 필요한가 ────────────────────────────────────────────────────

새마을금고·농·축협 금리 화면에는 금고 이름도 주소도 없다. 그래서 취급
상품과 금리가 같은 두 금고는 응답 바이트가 완전히 같아진다. **그것 자체는
정상이다** — 두 금고가 같은 금리를 주고 있다는 뜻이다.

문제는 원천이 고장 났을 때도 똑같이 보인다는 것이다. 2026-08-06 실행에서
경남 186장이 전부 같은 응답으로 왔고, 그때 수집기는 중복이라 보고 통째로
버렸다. 관측 7,274건이 사라졌는데 오류도 경고도 0이었다.

이제는 버리지 않는다 (마이그레이션 `f27b5e9c1a48`). 대신 **얼마나
되풀이되는지 세어서 남기고**, 정상이라고 보기 어려운 수준이면 멈춘다.

── 왜 "연속"으로 세는가 ───────────────────────────────────────────

전체 비율로 재면 정상과 고장이 안 갈린다. 표준 상품만 취급하는 금고가
전국에 흩어져 있으면 중복률이 자연히 높다. 반대로 원천이 고장 나면 **한
지역이 통째로** 같은 응답을 준다 — 경남이 그랬다.

그래서 **연속으로 같은 응답이 몇 번 왔는가**를 본다. 서로 다른 조회
인자에 같은 답이 줄줄이 오는 것은 "그 금고들이 우연히 금리가 같다"보다
"원천이 조회를 무시하고 있다"에 훨씬 가깝다.
"""

from dataclasses import dataclass, field

# 연속 몇 장까지 봐주는가.
#
# 경남은 **186장 연속**이었다. 정상 실행에서 관측된 최장 연속은 그보다
# 훨씬 짧다 — 금고마다 취급 상품이 달라서 거치식·적립식이 번갈아 오고,
# 같은 값이 길게 이어지지 않는다.
#
# 40으로 둔 것은 경남(186)보다 한참 낮고, 지역 하나가 통째로 같은 응답을
# 주는 상황을 잡되, 표준 상품이 몇십 곳 이어지는 정도는 통과시키기
# 위해서다. 실측이 쌓이면 조정한다 — 지금은 관측된 고장(186)과 정상 사이
# 어디에도 실측 경계가 없다.
MAX_CONSECUTIVE_REPEATS = 40


@dataclass
class RepeatGuard:
    """같은 응답이 연속으로 몇 번 왔는지 센다."""

    limit: int = MAX_CONSECUTIVE_REPEATS
    total: int = 0
    """전체 응답 수."""

    repeats: int = 0
    """앞에 이미 본 적 있는 응답이었던 횟수. 정상일 수 있다."""

    longest_run: int = 0
    """연속으로 같은 응답이 온 최장 길이."""

    _seen: set[bytes] = field(default_factory=set, repr=False)
    _last: bytes | None = field(default=None, repr=False)
    _run: int = field(default=0, repr=False)

    def observe(self, body: bytes, *, where: str) -> None:
        """응답 하나를 본다. 연속 한도를 넘으면 `RepeatedResponseError`.

        >>> guard = RepeatGuard(limit=3)
        >>> for _ in range(2):
        ...     guard.observe(b"same", where="1203")
        >>> guard.repeats
        1

        서로 다른 응답이 끼면 연속이 끊긴다.

        >>> guard.observe(b"other", where="1204")
        >>> guard.observe(b"same", where="1205")
        >>> guard.longest_run
        2

        한도를 넘으면 멈춘다. 원천이 조회를 무시하고 있다는 신호다.

        >>> guard = RepeatGuard(limit=2)
        >>> try:
        ...     for i in range(3):
        ...         guard.observe(b"same", where=f"{i}")
        ... except RepeatedResponseError as stop:
        ...     print(str(stop).splitlines()[0])
        같은 응답이 3번 연속으로 왔다 (마지막 조회: '2').
        """
        self.total += 1
        if body in self._seen:
            self.repeats += 1
        else:
            self._seen.add(body)

        self._run = self._run + 1 if body == self._last else 1
        self._last = body
        self.longest_run = max(self.longest_run, self._run)

        if self._run > self.limit:
            raise RepeatedResponseError(
                f"같은 응답이 {self._run}번 연속으로 왔다 (마지막 조회: {where!r}).\n"
                "원천이 조회 인자를 무시하고 있을 수 있다"
            )

    def summary(self) -> str:
        """실행 기록에 남길 한 줄. **되풀이가 없어도 적는다.**

        0건일 때 아무 말도 안 하면, 다음 사람이 "이 실행은 검사를 안 했나"와
        "검사했는데 0이었나"를 구별할 수 없다.

        >>> RepeatGuard().summary()
        '응답 0장 · 되풀이 0장 · 최장 연속 0'
        """
        return (
            f"응답 {self.total:,}장 · 되풀이 {self.repeats:,}장"
            f" · 최장 연속 {self.longest_run:,}"
        )


class RepeatedResponseError(RuntimeError):
    """원천이 서로 다른 조회에 같은 답을 되풀이한다.

    `SourceBlockedError`와 나눠 둔다. 차단은 원천이 우리를 막은 것이고,
    이쪽은 원천이 답은 주는데 그 답이 조회와 무관한 것이다. 대응이 다르다 —
    앞엣것은 물러나야 하고, 뒤엣것은 사람이 원본을 봐야 한다.
    """
