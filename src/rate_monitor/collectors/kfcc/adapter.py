"""새마을금고 공식 페이지 어댑터.

fetch()만 담당한다. 파싱은 parser가, 저장은 오케스트레이터가 한다
(명세서 v3 §6.2).

두 단계로 돈다 (docs/source-recon/kfcc.md).

    1. 지역마다 목록       GET /map/list.do?r1={지역}&r2=
    2. 금고마다 상품군별   GET /map/goods_19.do?OPEN_TRMID=&gubuncode=

`r2`를 비우면 그 지역 전체가 한 번에 온다 (2026-08-05 실측: 부산 = 273점포
137금고, 1회). 그래서 시군구 목록을 들고 다닐 필요가 없다. 예전에는 부산
16개 구를 config에 적어두고 16회를 돌았는데, 목록을 손으로 관리해야 했고
"부산"이 코드 구조에 박히는 원인이었다. 지금은 부산이 수집 단위가 아니라
`config/regions.yaml`의 수집 범위 하나일 뿐이고, 전국도 같은 경로로 돈다.

`r1`은 행정구역 시도가 아니라 사이트의 지역본부 묶음이다. 수집 범위를 고르는
데만 쓰고, 지역 표시는 언제나 점포 주소에서 뽑는다 (`parser.split_region`).

금리는 `gmgoCd`당 한 번만 받는다. 점포 수만큼 복제하지 않는다 (v3 §7.3.4-6).
부산 기준 점포 273개 대비 금고 137개라 요청이 절반으로 줄고 중복 행도 안 생긴다.

차단 우회는 하지 않는다 (v3 §0.2, §16.1). 차단이 보이면 즉시 멈춘다.
일시적인 연결/timeout/5xx만 제한적으로 다시 시도하며 정상 요청 간격 1초는
줄이지 않는다 (`20260811-resumable-acquisition-v1.md` §23).
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import yaml

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.kfcc import parser
from rate_monitor.collectors.repeat_guard import RepeatGuard
from rate_monitor.domain.enums import (
    CollectionMode,
    JoinChannel,
    Sector,
    SourceRole,
    TrustLevel,
)
from rate_monitor.domain.schemas import CollectionRequest, ParsedRateRow, RawArtifactData

logger = logging.getLogger(__name__)

BASE_URL = "https://www.kfcc.co.kr"
REGIONS_PATH = Path("config/regions.yaml")

# 우리를 밝히는 User-Agent.
#
# 2026-08-05 실측: 같은 URL이 httpx 기본 UA(`python-httpx/0.28.1`)로는
# `400 Request Blocked`, 우리 이름으로는 `200`이다. 라이브러리 기본값을
# 거부하는 규칙이 있는 것으로 보인다.
#
# 이것은 명세서 v3 §7.3.8이 금지한 "User-Agent 위장"이 아니다. 브라우저인
# 척하는 것이 정확히 그 금지 대상이고, 여기서는 반대로 우리가 누구인지
# 이름과 목적을 밝힌다. 크롤러 예절의 기본이기도 하다.
#
# HTTP 헤더는 ASCII만 담을 수 있으므로 한글을 넣지 않는다.
USER_AGENT = "rate-monitor/1 (+public rate disclosure collector; 1 req/s)"

# 명세서 v3 §7.3.8 요청 제어
REQUEST_INTERVAL_SECONDS = 1.0
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 20.0

# transient failure만 제한적으로 다시 시도한다. 목록은 뒤의 모든 금리 요청을
# 가능하게 하는 선행 단계라 한 번 더 기다리고, 금리 요청은 SLA 여유를 지키기
# 위해 더 짧게 끝낸다. 실제 retry 대기에도 정상 1초 요청 간격을 더한다.
LIST_RETRY_BACKOFF_SECONDS = (5.0, 20.0, 60.0)
RATE_RETRY_BACKOFF_SECONDS = (3.0, 12.0)
RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})
MAX_TOTAL_RETRIES = 50

# 수집 대상 상품군. 요구불(12)은 단계금액 구간 파싱이 따로 필요해 미룬다.
DEFAULT_GROUPS = ("13", "14")

# 폭주 방지.
#   부산  = 목록   1 + 금고   137 × 2 =   275회 (약 5분)
#   전국  = 목록  17 + 금고 1,260 × 2 = 2,537회 (약 42분)
# 전국을 다 돌고도 남을 만큼만 둔다. 이 값에 닿았다면 원천 구조가 바뀐 것이다.
# retry는 별도 MAX_TOTAL_RETRIES로 제한하므로 실제 HTTP 시도는 이 값보다 최대
# 그만큼 더 많을 수 있다.
MAX_REQUESTS = 4000

# 새마을금고는 차단 시 200이 아니라 400에 이 문구를 실어 보낸 이력이 있다.
# finlife처럼 403/429만 보면 이 경우를 놓친다.
BLOCK_MARKERS = ("Request Blocked", "Access Denied")
BLOCK_STATUSES = (400, 403, 429)

Sleep = Callable[[float], Awaitable[None]]


class KfccRequestFailure(RuntimeError):
    """KFCC 요청이 bounded retry 뒤에도 실패했음을 구조화해 남긴다."""

    def __init__(
        self,
        code: str,
        *,
        phase: str,
        request_label: str,
        attempt: int,
        max_attempts: int,
        cause: Exception,
        retry_count: int,
        failure_reasons: dict[str, int] | None = None,
    ) -> None:
        self.code = code
        self.phase = phase
        self.request_label = request_label
        self.attempt = attempt
        self.max_attempts = max_attempts
        self.cause = cause
        self.retry_count = retry_count
        self.failure_reasons = dict(failure_reasons or {})
        reasons = ", ".join(
            f"{reason} {count}" for reason, count in sorted(self.failure_reasons.items())
        ) or "none"
        super().__init__(
            f"{code}: phase={phase} request={request_label} "
            f"attempt={attempt}/{max_attempts} retries={retry_count} "
            f"failures={reasons} cause={type(cause).__name__}: {cause}"
        )


def _failure_code(exc: Exception) -> str:
    """실제로 구별할 수 있는 transient 실패만 분류한다."""
    if isinstance(exc, httpx.ConnectError):
        return "NETWORK_CONNECT"
    if isinstance(
        exc,
        (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout),
    ):
        return "NETWORK_TIMEOUT"
    if isinstance(exc, (httpx.ReadError, httpx.WriteError)):
        return "NETWORK_IO"
    if isinstance(exc, httpx.RemoteProtocolError):
        return "NETWORK_PROTOCOL"
    if (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in RETRYABLE_STATUS_CODES
    ):
        return "HTTP_SERVER_ERROR"
    return "NETWORK_UNKNOWN"


class KfccAdapter:
    """새마을금고 예탁금 금리 수집기."""

    source_id = "kfcc"
    source_role = SourceRole.PRIMARY_OFFICIAL
    trust_level = TrustLevel.OFFICIAL_DIRECT

    source_name = "새마을금고 금고위치안내"
    sector = Sector.KFCC
    mode = CollectionMode.HTTP
    priority = 10
    base_reference = "kfcc.co.kr/map"
    # 이용약관·자동수집 정책을 확인하지 못했다. allowed로 올리지 않는다.
    policy_status = "review"
    # 공식 화면에 최고우대금리 열 자체가 없다. 저장값은 전부 NULL이어야 한다.
    provides_max_rate = False
    coverage_status = "partial"

    # 금리가 창구판매 기준이라는 안내는 이 금리 페이지가 아니라 그것을 감싸는
    # view.do에 있다. 금리 페이지만 받아서는 알 수 없으므로 원천의 성질로
    # 여기서 명시한다 (docs/source-recon/kfcc.md §2.2).
    join_channel = JoinChannel.BRANCH

    def __init__(self, regions_path: Path | None = None, *, sleep: Sleep | None = None) -> None:
        self._regions_path = regions_path or REGIONS_PATH
        self._sleep = sleep or asyncio.sleep
        self._retry_count = 0
        self._retry_reasons: Counter[str] = Counter()

    # ── 지역 ────────────────────────────────────────────────────────────

    def _load_regions(self, request: CollectionRequest) -> list[str]:
        """수집할 `r1` 지역 목록을 정한다.

        고르는 순서는 세 가지다.

            1. `request.regions`        — 지역을 직접 지정 (예: 부산)
            2. `request.options["scope"]` — config의 수집 범위 이름 (예: 수도권)
            3. config의 `default_scope`

        지역 목록을 코드에 박지 않는다 (v3 §7.3.4-8). 어느 경로로 오든 값은
        config가 아는 것이어야 하고, 모르는 값은 조용히 넘기지 않는다.
        """
        config = yaml.safe_load(self._regions_path.read_text(encoding="utf-8"))
        scopes = {s["name"]: list(s["kfcc_r1"]) for s in config["scopes"]}
        known = {region for regions in scopes.values() for region in regions}

        if request.regions:
            unknown = [r for r in request.regions if r not in known]
            if unknown:
                raise ValueError(f"config에 없는 지역: {unknown}")
            # 같은 지역을 두 번 적어도 두 번 돌지 않는다.
            return list(dict.fromkeys(request.regions))

        name = request.options.get("scope") or config["default_scope"]
        if name not in scopes:
            raise ValueError(
                f"config에 없는 수집 범위: {name!r} (가능: {sorted(scopes)})"
            )
        return scopes[name]

    # ── 요청 ────────────────────────────────────────────────────────────

    def _reset_retry_state(self) -> None:
        self._retry_count = 0
        self._retry_reasons.clear()

    def _retry_note(self) -> str:
        if not self._retry_count:
            return ""
        reasons = ", ".join(
            f"{code} {count}" for code, count in sorted(self._retry_reasons.items())
        )
        return f"재시도 {self._retry_count}회 ({reasons})"

    def _failure_reasons_with(self, code: str) -> dict[str, int]:
        reasons = Counter(self._retry_reasons)
        reasons[code] += 1
        return dict(sorted(reasons.items()))

    def _reserve_retry(
        self,
        *,
        code: str,
        phase: str,
        request_label: str,
        attempt: int,
        max_attempts: int,
        cause: Exception,
    ) -> None:
        if self._retry_count >= MAX_TOTAL_RETRIES:
            raise KfccRequestFailure(
                "RETRY_BUDGET_EXHAUSTED",
                phase=phase,
                request_label=request_label,
                attempt=attempt,
                max_attempts=max_attempts,
                cause=cause,
                retry_count=self._retry_count,
                failure_reasons=self._failure_reasons_with(code),
            ) from cause
        self._retry_count += 1
        self._retry_reasons[code] += 1

    @staticmethod
    def _request_label(phase: str, params: dict[str, str]) -> str:
        if phase == "list":
            return f"r1={params.get('r1', '')}"
        if phase == "rate":
            return (
                f"gmgoCd={params.get('OPEN_TRMID', '')} "
                f"gubuncode={params.get('gubuncode', '')}"
            )
        return phase

    @staticmethod
    def _request_phase(url: str) -> str:
        if url.endswith("/map/list.do"):
            return "list"
        if url.endswith("/map/goods_19.do"):
            return "rate"
        raise ValueError(f"알 수 없는 KFCC 요청 endpoint: {url!r}")

    async def _get(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str],
    ) -> bytes:
        """GET 하나를 수행하되 transient failure만 제한적으로 다시 시도한다."""
        phase = self._request_phase(url)
        backoffs = (
            LIST_RETRY_BACKOFF_SECONDS if phase == "list" else RATE_RETRY_BACKOFF_SECONDS
        )
        max_attempts = len(backoffs) + 1
        request_label = self._request_label(phase, params)

        for attempt in range(1, max_attempts + 1):
            failure: Exception | None = None
            code = ""
            http_status: int | None = None
            try:
                response = await client.get(url, params=params)
                body = response.content
                if response.status_code in BLOCK_STATUSES:
                    text = body.decode("utf-8", "ignore")
                    if any(marker in text for marker in BLOCK_MARKERS):
                        raise SourceBlockedError(
                            f"차단 응답 {response.status_code}: {url} — 우회하지 않고 중단한다"
                        )
                response.raise_for_status()
                return body
            except SourceBlockedError:
                raise
            except httpx.HTTPStatusError as exc:
                http_status = exc.response.status_code
                if http_status not in RETRYABLE_STATUS_CODES:
                    raise
                failure = exc
                code = "HTTP_SERVER_ERROR"
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.ReadError,
                httpx.WriteError,
                httpx.RemoteProtocolError,
            ) as exc:
                failure = exc
                code = _failure_code(exc)

            assert failure is not None
            if attempt >= max_attempts:
                raise KfccRequestFailure(
                    code,
                    phase=phase,
                    request_label=request_label,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    cause=failure,
                    retry_count=self._retry_count,
                    failure_reasons=self._failure_reasons_with(code),
                ) from failure

            self._reserve_retry(
                code=code,
                phase=phase,
                request_label=request_label,
                attempt=attempt,
                max_attempts=max_attempts,
                cause=failure,
            )
            delay = REQUEST_INTERVAL_SECONDS + backoffs[attempt - 1]
            logger.warning(
                "KFCC retry source_id=%s phase=%s request=%s attempt=%d max_attempts=%d "
                "error_class=%s http_status=%s retry_delay=%.1f",
                self.source_id,
                phase,
                request_label,
                attempt,
                max_attempts,
                code,
                http_status if http_status is not None else "-",
                delay,
            )
            await self._sleep(delay)

        raise AssertionError("KFCC retry loop exhausted without returning or raising")

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        self._reset_retry_state()
        regions = self._load_regions(request)
        groups = tuple(request.options.get("groups") or DEFAULT_GROUPS)

        artifacts: list[RawArtifactData] = []
        # **바이트가 같아도 버리지 않는다.**
        #
        # 예전에는 여기서 걸렀다. `raw_artifacts`의 유일성이
        # `(run_id, sha256)`이라 같은 내용을 두 번 못 넣었기 때문이다.
        # 그런데 금리 화면에는 금고 이름도 주소도 없어서, 취급 상품과 금리가
        # 같은 두 금고는 응답이 완전히 같아진다. 뒤에 온 금고가 통째로
        # 버려졌고 **DB에 아예 안 생겼다** — 2026-08-06 실행에서 경남 186장,
        # 관측 7,274건이 그렇게 사라졌는데 오류도 경고도 0이었다.
        #
        # 이제 버리지 않는다. `save_raw_artifacts`가 같은 바이트끼리 원본
        # 행 **하나를 함께 가리키게** 해서 제약을 지킨다 — 조회는 하나도
        # 안 사라진다.
        #
        # 대신 얼마나 되풀이되는지 세어 남기고, 한 지역이 통째로 같은 응답을
        # 주는 수준이면 그만 받는다. **받은 것은 버리지 않고 돌려준다.**
        guard = RepeatGuard()
        requests_made = 0

        timeout = httpx.Timeout(
            connect=CONNECT_TIMEOUT,
            read=READ_TIMEOUT,
            write=READ_TIMEOUT,
            pool=CONNECT_TIMEOUT,
        )
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            # 1단계: 지역 목록. `r2`를 비워 지역 전체를 한 번에 받는다.
            outlets: dict[str, dict[str, str]] = {}
            # 금고마다 **모든** 점포를 모은다. 대표 하나만 두면 두 구에 걸친
            # 금고가 한쪽 구에서 사라진다 (부산 실측 3건).
            directory: dict[str, list[dict[str, str]]] = {}
            for region in regions:
                params = {"r1": region, "r2": ""}
                body = await self._get(client, f"{BASE_URL}/map/list.do", params)
                requests_made += 1
                guard.observe(body, where=f"list r1={region}")
                artifacts.append(
                    self._artifact(
                        body,
                        filename=f"list_{region}.html",
                        meta={"kind": "list", "r1": region, "r2": ""},
                    )
                )
                for row in parser.parse_list(body.decode("utf-8", "replace")):
                    # 금고 대표 행은 먼저 본 것을 쓴다. 금리는 금고 단위라
                    # 어느 점포 행을 쓰든 같다.
                    outlets.setdefault(row["gmgoCd"], row)
                    entries = directory.setdefault(row["gmgoCd"], [])
                    if not any(e["divCd"] == row.get("divCd") for e in entries):
                        entries.append(row)
                await self._sleep(REQUEST_INTERVAL_SECONDS)

            # 2단계: 금고별 금리
            for gmgo_cd, row in outlets.items():
                # 원천이 조회를 무시하고 있다면 더 받아 봐야 같은 답이다.
                # **그만 받되 지금까지 받은 것은 그대로 돌려준다** — 두 시간을
                # 받고 나서 통째로 버리면 원래 고치려던 손실과 같은 일이 된다.
                if guard.tripped:
                    break
                for group in groups:
                    if requests_made >= MAX_REQUESTS:
                        raise SourceBlockedError(
                            f"요청 상한 {MAX_REQUESTS}회에 도달했다. 설정을 확인한다"
                        )
                    params = {"OPEN_TRMID": gmgo_cd, "gubuncode": group}
                    body = await self._get(client, f"{BASE_URL}/map/goods_19.do", params)
                    requests_made += 1
                    await self._sleep(REQUEST_INTERVAL_SECONDS)
                    # 축은 상품구분이다. 금고는 바뀌고 구분은 고정인 흐름
                    # 안에서 봐야 "이 지역이 통째로 같은 답을 준다"가 보인다.
                    guard.observe(
                        body,
                        where=f"gmgoCd={gmgo_cd} gubuncode={group}",
                        stream=group,
                    )

                    artifacts.append(
                        self._artifact(
                            body,
                            filename=f"rate_{gmgo_cd}_{group}.html",
                            meta={
                                "kind": "rate",
                                "gmgoCd": gmgo_cd,
                                "gubuncode": group,
                                "r1": row.get("r1"),
                                "r2": row.get("r2"),
                                # 금리 페이지에는 금고 이름·주소가 없다.
                                # 파서가 붙일 수 있게 목록 행을 실어 보낸다.
                                "outlet": row,
                                # 이 금고의 점포 전부. 구 귀속에 쓴다.
                                "outlet_directory": directory.get(gmgo_cd, [row]),
                            },
                        )
                    )
        self.fetch_note = guard.summary()
        retry_note = self._retry_note()
        if retry_note:
            self.fetch_note = f"{self.fetch_note} · {retry_note}"
        self.fetch_alert = guard.tripped
        return artifacts

    def _artifact(self, body: bytes, *, filename: str, meta: dict) -> RawArtifactData:
        fingerprint = (
            parser.schema_fingerprint(body.decode("utf-8", "replace"))
            if meta["kind"] == "rate"
            else "list"
        )
        return RawArtifactData(
            artifact_type="html",
            content=body,
            filename=filename,
            # 인증키가 없는 원천이라 마스킹할 값이 없다. 그래도 쿠키·토큰을
            # 넣지 않는다는 규율은 그대로 지킨다.
            request_meta=meta,
            schema_fingerprint=fingerprint,
            source_role=self.source_role,
            trust_level=self.trust_level,
        )

    # ── 파싱 ────────────────────────────────────────────────────────────

    def parse(self, artifact: RawArtifactData) -> list[ParsedRateRow]:
        rows, _ = self.parse_with_warnings(artifact)
        return rows

    def parse_with_warnings(
        self, artifact: RawArtifactData
    ) -> tuple[list[ParsedRateRow], list[str]]:
        """아티팩트 종류에 따라 갈라진다.

        목록은 금리 행을 만들지 않는다. 구조 검사만 하고 빈 목록을 돌려준다.
        """
        html = artifact.content.decode("utf-8", "replace")
        meta: dict[str, Any] = artifact.request_meta
        if meta.get("kind") == "list":
            return [], parser.check_list_schema(html)

        return parser.parse_rates(
            html,
            gubuncode=str(meta["gubuncode"]),
            outlet=meta["outlet"],
            outlet_directory=meta.get("outlet_directory") or [],
            join_channel=self.join_channel,
        )