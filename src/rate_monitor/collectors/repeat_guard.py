"""원천이 같은 응답을 되풀이하고 있는지 지켜본다.

── 왜 필요한가 ────────────────────────────────────────────────────

새마을금고·농·축협 금리 화면에는 금고 이름도 주소도 없다. 그래서 취급
상품과 금리가 같은 두 금고는 응답 바이트가 완전히 같아진다. **그것 자체는
정상이다** — 두 금고가 같은 금리를 주고 있다는 뜻이다.

문제는 원천이 고장 났을 때도 똑같이 보인다는 것이다. 2026-08-06 실행에서
경남 186장이 전부 같은 응답으로 왔고, 그때 수집기는 중복이라 보고 통째로
버렸다. 관측 7,274건이 사라졌는데 오류도 경고도 0이었다.

이제는 버리지 않는다 — `save_raw_artifacts`가 같은 바이트끼리 원본 행 하나를
함께 가리키게 해서 제약을 지킨다. 대신 **얼마나
되풀이되는지 세어서 남기고**, 정상이라고 보기 어려운 수준이면 멈춘다.

── 왜 "연속"으로 세는가 ───────────────────────────────────────────

전체 비율로 재면 정상과 고장이 안 갈린다. 표준 상품만 취급하는 금고가
전국에 흩어져 있으면 중복률이 자연히 높다. 반대로 원천이 고장 나면 **한
지역이 통째로** 같은 응답을 준다 — 경남이 그랬다.

그래서 **연속으로 같은 응답이 몇 번 왔는가**를 본다. 서로 다른 조회
인자에 같은 답이 줄줄이 오는 것은 "그 금고들이 우연히 금리가 같다"보다
"원천이 조회를 무시하고 있다"에 훨씬 가깝다.

── 축마다 따로 센다 ──────────────────────────────────────────────

**여기서 한 번 틀렸다.** 처음에는 응답이 오는 순서 그대로 연속을 셌는데,
수집기는 축을 두 개 돈다 — 금고마다 예금(13)·적금(14)을 번갈아 받는다.
그러면 경남처럼 통째로 같은 답이 와도 순서가 `A13, A14, B13, B14…`라
바로 앞과는 늘 달라서 연속이 1로 끊긴다.

    경남 재현 (93금고 × 2구분)
    → 응답 186장 · 되풀이 184장 · **최장 연속 1**   ← 못 잡는다

그래서 `stream`(조회 축)마다 따로 센다. 금고는 바뀌고 구분은 고정인 흐름
안에서 보면 경남은 93장 연속이 된다. 호출자가 자기 축을 알려줘야 한다.
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

    tripped: str = ""
    """한도를 넘었을 때의 사유. 비어 있으면 정상이다.

    **예외를 던지지 않는다.** 던지면 그때까지 모은 것이 통째로 버려진다 —
    새마을금고는 두 시간을 받고 나서 멈출 수도 있는데, 그 데이터를 잃는 것은
    원래 고치려던 손실과 같은 일이다. 수집기는 여기서 그만 받고, 받은 것은
    돌려준다.
    """

    _seen: set[bytes] = field(default_factory=set, repr=False)
    _last: dict[str, bytes] = field(default_factory=dict, repr=False)
    _run: dict[str, int] = field(default_factory=dict, repr=False)

    def observe(self, body: bytes, *, where: str, stream: str = "") -> None:
        """응답 하나를 본다. 연속 한도를 넘으면 `tripped`에 사유를 적는다.

        `stream`은 조회 축이다. 수집기가 축을 둘 돌면(금고 × 상품구분) 축을
        갈라 줘야 연속이 제대로 세어진다.

        >>> guard = RepeatGuard(limit=3)
        >>> for _ in range(2):
        ...     guard.observe(b"same", where="1203")
        >>> guard.repeats
        1

        같은 축 안에서 다른 응답이 끼면 연속이 끊긴다.

        >>> guard.observe(b"other", where="1204")
        >>> guard.observe(b"same", where="1205")
        >>> guard.longest_run
        2

        **축이 다르면 서로 연속을 끊지 않는다.** 이게 경남을 놓쳤던 곳이다 —
        금고마다 예금·적금을 번갈아 받아 바로 앞과는 늘 달랐다.

        >>> guard = RepeatGuard(limit=3)
        >>> for i in range(4):
        ...     for group in ("13", "14"):
        ...         guard.observe(f"generic-{group}".encode(),
        ...                       where=f"{i}/{group}", stream=group)
        >>> guard.longest_run
        4

        한도를 넘으면 사유를 남긴다. 예외는 던지지 않는다.

        >>> guard = RepeatGuard(limit=2)
        >>> for i in range(3):
        ...     guard.observe(b"same", where=f"{i}")
        >>> print(guard.tripped.splitlines()[0])
        같은 응답이 3번 연속으로 왔다 (마지막 조회: '2').
        """
        self.total += 1
        if body in self._seen:
            self.repeats += 1
        else:
            self._seen.add(body)

        run = self._run.get(stream, 0) + 1 if self._last.get(stream) == body else 1
        self._last[stream] = body
        self._run[stream] = run
        self.longest_run = max(self.longest_run, run)

        if run > self.limit and not self.tripped:
            self.tripped = (
                f"같은 응답이 {run}번 연속으로 왔다 (마지막 조회: {where!r}).\n"
                "원천이 조회 인자를 무시하고 있을 수 있다"
            )

    def summary(self) -> str:
        """실행 기록에 남길 한 줄. **되풀이가 없어도 적는다.**

        0건일 때 아무 말도 안 하면, 다음 사람이 "이 실행은 검사를 안 했나"와
        "검사했는데 0이었나"를 구별할 수 없다.

        >>> RepeatGuard().summary()
        '응답 0장 · 되풀이 0장 · 최장 연속 0'
        """
        note = (
            f"응답 {self.total:,}장 · 되풀이 {self.repeats:,}장"
            f" · 최장 연속 {self.longest_run:,}"
        )
        return f"{note} · **되풀이 한도 초과로 중단**" if self.tripped else note


class RepeatedResponseError(RuntimeError):
    """원천이 서로 다른 조회에 같은 답을 되풀이한다.

    `SourceBlockedError`와 나눠 둔다. 차단은 원천이 우리를 막은 것이고,
    이쪽은 원천이 답은 주는데 그 답이 조회와 무관한 것이다. 대응이 다르다 —
    앞엣것은 물러나야 하고, 뒤엣것은 사람이 원본을 봐야 한다.

    **수집 중에는 던지지 않는다.** `RepeatGuard.tripped`에 사유를 남기고
    수집기가 그만 받는다. 받은 것은 그대로 돌려주고, 실행은 검수항목과 함께
    `partial`로 끝난다.
    """
