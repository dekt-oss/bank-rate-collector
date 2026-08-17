"""농·축협 금융상품몰 어댑터 (v4 §5, PR 4).

fetch()만 담당한다. 파싱은 parser가, 저장은 오케스트레이터가 한다
(명세서 v3 §6.2).

계약은 `docs/source-recon/nh-local.md` §0.2에 실측으로 적혀 있다. 로그인도
세션도 쿠키도 없이 GET 두 종류면 끝난다.

    1. 명부   GET /servlet/SFDPW0161R.view                 전국 4,871행, 한 번에
    2. 금리   GET /servlet/SFDPW016{2,3,4}R.view?brc=...   점포·상품분류마다

**원천이 지역 요청 인자를 주지 않는다.** 명부가 통째로 오므로 범위는 받아
온 뒤 주소로 정한다 (`config/regions.yaml`의 `nh_local_address_prefixes`).
새마을금고처럼 지역별로 요청을 나눌 수가 없다.

그래서 요청 수가 점포 수에 정비례한다 — 부산 119점포면 239회(약 4분),
전국이면 9,743회(약 2시간 43분)다. 기본 범위는 현재 전국이며 config가 그
값을 갖고 있다.

차단 우회는 하지 않는다 (v3 §0.2, §16.1). 차단이 보이면 즉시 멈춘다.
일시적인 연결/timeout/5xx만 제한적으로 다시 시도하며 정상 요청 간격 1초는
줄이지 않는다 (`20260811-nh-kfcc-reliability-sla-v1.md`).
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import yaml

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.nh_local import parser
from rate_monitor.collectors.nh_local.parser import NhOutlet
from rate_monitor.collectors.repeat_guard import RepeatGuard
from rate_monitor.domain.enums import (
    CollectionMode,
    ProductType,
    Sector,
    SourceRole,
    TrustLevel,
)
from rate_monitor.domain.schemas import CollectionRequest, ParsedRateRow, RawArtifactData
from rate_monitor.domain.timeutil import now_kst

logger = logging.getLogger(__name__)

BASE_URL = "https://wmall.nonghyup.com"
LIST_SCREEN = "SFDPW0161R"
REGIONS_PATH = Path("config/regions.yaml")

# 우리를 밝히는 User-Agent. 브라우저인 척하지 않는다 (v3 §7.3.8).
# HTTP 헤더는 ASCII만 담을 수 있으므로 한글을 넣지 않는다.
USER_AGENT = "rate-monitor/1 (+public rate disclosure collector; 1 req/s)"

REQUEST_INTERVAL_SECONDS = 1.0
CONNECT_TIMEOUT = 10.0
# 명부가 3.1 MB다. 금리 화면(121 KB)보다 훨씬 오래 걸린다.
READ_TIMEOUT = 60.0

# 일시 장애에만 적용하는 bounded retry. tuple의 각 값은 다음 시도 전에 더하는
# backoff이고, 실제 대기에는 정상 요청 간격 1초도 함께 들어간다.
PREFLIGHT_RETRY_BACKOFF_SECONDS = (5.0, 20.0, 60.0)
DETAIL_RETRY_BACKOFF_SECONDS = (3.0, 12.0)
RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})
MAX_TOTAL_RETRIES = 50
# 07:30 normal 목표의 관측 최소 여유가 약 10분이었다. retry backoff가
# 그 여유를 25분까지 잠식하지 않도록, 실제로 sleep하는 누적 추가 대기를
# 10분으로 별도 제한한다. 요청 자체 timeout은 기존 per-request 제한을 따른다.
MAX_TOTAL_RETRY_DELAY_SECONDS = 10 * 60.0

# 수집할 상품 분류.
#
# 입출금식(`SFDPW0162R`)은 **뺀다.** 그 화면의 실물을 아직 한 번도 못 봤고,
# 파서가 본 적 없는 표를 상대로 열 위치를 맞다고 가정할 수 없다 (v4 §0.2).
# fixture를 확보한 뒤에 넣는다.
DEFAULT_PRODUCTS = (ProductType.TERM_DEPOSIT, ProductType.INSTALLMENT_SAVINGS)

# 폭주 방지. 전국 2화면(9,743회)을 넘기면 원천 구조가 바뀐 것이다.
MAX_REQUESTS = 12000

BLOCK_MARKERS = ("Request Blocked", "Access Denied", "접속이 차단")
BLOCK_STATUSES = (400, 403, 429)

Sleep = Callable[[float], Awaitable[None]]


class NhRequestFailure(RuntimeError):
    """NH 요청이 bounded retry 뒤에도 실패했음을 구조화해 남긴다."""

    def __init__(
        self,
        code: str,
        *,
        phase: str,
        screen: str,
        attempt: int,
        max_attempts: int,
        cause: Exception,
        retry_count: int,
        failure_reasons: dict[str, int] | None = None,
    ) -> None:
        self.code = code
        self.phase = phase
        self.screen = screen
        self.attempt = attempt
        self.max_attempts = max_attempts
        self.cause = cause
        self.retry_count = retry_count
        self.failure_reasons = dict(failure_reasons or {})
        reasons = ", ".join(
            f"{reason} {count}" for reason, count in sorted(self.failure_reasons.items())
        ) or "none"
        super().__init__(
            f"{code}: phase={phase} screen={screen} attempt={attempt}/{max_attempts} "
            f"retries={retry_count} failures={reasons} "
            f"cause={type(cause).__name__}: {cause}"
        )


def _failure_code(exc: Exception) -> str:
    """실제로 구별할 수 있는 네트워크 실패만 분류한다."""
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


class NhLocalAdapter:
    """지역 농·축협 예탁금 금리 수집기."""

    source_id = "nh_local"
    # 농협중앙회가 조합을 대신해 공시하는 화면이다. 조합 자신의 공시가 아니다.
    source_role = SourceRole.SECONDARY_OFFICIAL
    trust_level = TrustLevel.OFFICIAL_DIRECT

    source_name = "농협 금융상품몰 농·축협별 예금금리"
    sector = Sector.NH_LOCAL
    mode = CollectionMode.HTTP
    priority = 10
    base_reference = "wmall.nonghyup.com/servlet/SFDPW0161R.view"
    # 사용자가 2026-08-06에 이용약관을 직접 확인했고 자동수집을 제한하는
    # 조항이 없었다. 확인한 사람이 있으므로 review에 두지 않는다.
    policy_status = "allowed"
    # 상세표에 최고우대금리 열이 없다 (정찰 §0.2).
    provides_max_rate = False
    # 입출금식 화면을 아직 안 받는다.
    coverage_status = "partial"

    def __init__(self, regions_path: Path | None = None, *, sleep: Sleep | None = None) -> None:
        self._regions_path = regions_path or REGIONS_PATH
        self._sleep = sleep or asyncio.sleep
        self._retry_count = 0
        self._retry_delay_seconds = 0.0
        self._retry_reasons: Counter[str] = Counter()

    # ── 범위 ────────────────────────────────────────────────────────────

    def _load_prefixes(self, request: CollectionRequest) -> tuple[str, ...] | None:
        """수집할 주소 접두어. `None`이면 전국이다.

        범위 이름은 config가 아는 것이어야 한다 (v3 §7.3.4-8). 모르는 이름을
        조용히 넘기면 0건 수집이 "그날은 금리가 없었다"처럼 보인다.
        """
        config = yaml.safe_load(self._regions_path.read_text(encoding="utf-8"))
        scopes = {s["name"]: s for s in config["scopes"]}

        name = request.options.get("scope") or config.get(
            "nh_local_default_scope", config["default_scope"]
        )
        if name not in scopes:
            raise ValueError(
                f"config에 없는 수집 범위: {name!r} (가능: {sorted(scopes)})"
            )
        prefixes = scopes[name].get("nh_local_address_prefixes")
        return None if prefixes is None else tuple(prefixes)

    # ── 요청 ────────────────────────────────────────────────────────────

    def _reset_retry_state(self) -> None:
        self._retry_count = 0
        self._retry_delay_seconds = 0.0
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
        screen: str,
        attempt: int,
        max_attempts: int,
        cause: Exception,
        delay: float,
    ) -> None:
        if self._retry_count >= MAX_TOTAL_RETRIES:
            raise NhRequestFailure(
                "RETRY_BUDGET_EXHAUSTED",
                phase=phase,
                screen=screen,
                attempt=attempt,
                max_attempts=max_attempts,
                cause=cause,
                retry_count=self._retry_count,
                failure_reasons=self._failure_reasons_with(code),
            ) from cause
        if self._retry_delay_seconds + delay > MAX_TOTAL_RETRY_DELAY_SECONDS:
            raise NhRequestFailure(
                "RETRY_DELAY_BUDGET_EXHAUSTED",
                phase=phase,
                screen=screen,
                attempt=attempt,
                max_attempts=max_attempts,
                cause=cause,
                retry_count=self._retry_count,
                failure_reasons=self._failure_reasons_with(code),
            ) from cause
        self._retry_count += 1
        self._retry_delay_seconds += delay
        self._retry_reasons[code] += 1

    async def _get(
        self,
        client: httpx.AsyncClient,
        screen: str,
        params: dict[str, str],
        *,
        phase: str,
    ) -> bytes:
        """GET 하나를 수행하되 transient failure만 제한적으로 다시 시도한다."""
        if phase == "preflight":
            backoffs = PREFLIGHT_RETRY_BACKOFF_SECONDS
        elif phase == "detail":
            backoffs = DETAIL_RETRY_BACKOFF_SECONDS
        else:
            raise ValueError(f"알 수 없는 NH 요청 phase: {phase!r}")

        max_attempts = len(backoffs) + 1
        url = f"{BASE_URL}/servlet/{screen}.view"

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
                raise NhRequestFailure(
                    code,
                    phase=phase,
                    screen=screen,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    cause=failure,
                    retry_count=self._retry_count,
                    failure_reasons=self._failure_reasons_with(code),
                ) from failure

            delay = REQUEST_INTERVAL_SECONDS + backoffs[attempt - 1]
            self._reserve_retry(
                code=code,
                phase=phase,
                screen=screen,
                attempt=attempt,
                max_attempts=max_attempts,
                cause=failure,
                delay=delay,
            )
            logger.warning(
                "NH retry source_id=%s phase=%s screen=%s attempt=%d max_attempts=%d "
                "error_class=%s http_status=%s retry_delay=%.1f cumulative_retry_delay=%.1f",
                self.source_id,
                phase,
                screen,
                attempt,
                max_attempts,
                code,
                http_status if http_status is not None else "-",
                delay,
                self._retry_delay_seconds,
            )
            await self._sleep(delay)

        raise AssertionError("NH retry loop exhausted without returning or raising")

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        self._reset_retry_state()
        prefixes = self._load_prefixes(request)
        products = tuple(request.options.get("products") or DEFAULT_PRODUCTS)
        # e-joy 우대행은 거치식 화면에 있고 적립식에도 적용된다. 거치식이
        # 요청에 포함된 경우에만 먼저 받아 같은 BRC 안에서 evidence를 운반한다.
        # 거치식이 빠진 custom 수집에서는 추가 요청을 만들지 않고 fail closed한다.
        if ProductType.TERM_DEPOSIT in products:
            products = (ProductType.TERM_DEPOSIT,) + tuple(
                product for product in products if product != ProductType.TERM_DEPOSIT
            )
        # 조회일이 곧 기준일이다. 원천이 별도 공시일을 주지 않는다 (정찰 §0.2).
        as_of = now_kst().date().isoformat()

        artifacts: list[RawArtifactData] = []
        # **바이트가 같아도 버리지 않는다.** 새마을금고와 같은 결함이 여기도
        # 있었다 — 점포별 금리 화면에 점포 이름이 없어서, 같은 금리를 주는 두
        # 점포는 응답이 똑같아지고 뒤엣것이 통째로 버려졌다.
        #
        # 지금은 부산 120점포뿐이라 안 드러났을 뿐이고, 전국(4,871점포)으로
        # 넓히면 새마을금고에서 난 일이 그대로 난다.
        #
        # `save_raw_artifacts`가 같은 바이트끼리 원본 행 하나를 함께
        # 가리키게 해서 제약을 지킨다. 대신 되풀이를 세어 남긴다.
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
            # 1단계: 전국 명부. 페이지네이션이 없다. 전국 수집의 전제라서
            # detail보다 한 번 더 retry할 수 있는 preflight 정책을 쓴다.
            body = await self._get(client, LIST_SCREEN, {}, phase="preflight")
            requests_made += 1
            guard.observe(body, where="outlet list")
            artifacts.append(
                self._artifact(
                    body,
                    filename="outlet_list.html",
                    meta={"kind": "list", "screen": LIST_SCREEN},
                )
            )
            await self._sleep(REQUEST_INTERVAL_SECONDS)

            outlets = parser.outlets_in(
                parser.parse_outlet_list(body.decode("utf-8", "replace")), prefixes
            )
            if not outlets:
                raise SourceBlockedError(
                    f"명부에서 범위에 맞는 점포가 하나도 없다 (접두어 {prefixes})"
                )

            # 2단계: 점포·상품분류별 금리
            for outlet in outlets:
                # 원천이 조회를 무시하면 그만 받되, 받은 것은 돌려준다.
                if guard.tripped:
                    break
                ejoy_options: list[dict[str, Any]] = []
                for product in products:
                    if requests_made >= MAX_REQUESTS:
                        raise SourceBlockedError(
                            f"요청 상한 {MAX_REQUESTS}회에 도달했다. 설정을 확인한다"
                        )
                    screen = parser.SCREEN_BY_PRODUCT[product]
                    body = await self._get(
                        client,
                        screen,
                        {
                            "brc": outlet.brc,
                            "brnm": outlet.name,
                            # 화면 기본값. 비운 채로 전부 온다 (정찰 §0.2).
                            "inq_dsc": "",
                            "inq_str": "",
                            "searchContent": "",
                        },
                        phase="detail",
                    )
                    requests_made += 1
                    await self._sleep(REQUEST_INTERVAL_SECONDS)
                    # 축은 화면이다. 점포는 바뀌고 화면은 고정인 흐름 안에서
                    # 봐야 "이 구간이 통째로 같은 답을 준다"가 보인다.
                    guard.observe(
                        body, where=f"brc={outlet.brc} screen={screen}", stream=screen
                    )

                    ejoy_warnings: list[str] = []
                    if product == ProductType.TERM_DEPOSIT:
                        ejoy_options, ejoy_warnings = parser.extract_ejoy_options(
                            body.decode("utf-8", "replace"), brc=outlet.brc
                        )

                    meta: dict[str, Any] = {
                        "kind": "rate",
                        "screen": screen,
                        "product_type": product.value,
                        "as_of": as_of,
                        # 금리 화면에도 점포명은 있지만 주소는 없다.
                        # 파서가 붙일 수 있게 명부 행을 실어 보낸다.
                        "outlet": outlet._asdict(),
                        # 같은 BRC의 거치식 공식 e-joy evidence만 전달한다.
                        "ejoy_options": ejoy_options,
                    }
                    if ejoy_warnings:
                        meta["ejoy_warnings"] = ejoy_warnings
                    artifacts.append(
                        self._artifact(
                            body,
                            filename=f"rate_{outlet.brc}_{screen}.html",
                            meta=meta,
                        )
                    )
        self.fetch_note = guard.summary()
        retry_note = self._retry_note()
        if retry_note:
            self.fetch_note = f"{self.fetch_note} · {retry_note}"
        self.fetch_alert = guard.tripped
        return artifacts

    def _artifact(self, body: bytes, *, filename: str, meta: dict) -> RawArtifactData:
        html = body.decode("utf-8", "replace")
        return RawArtifactData(
            artifact_type="html",
            content=body,
            filename=filename,
            # 인증키가 없는 원천이라 마스킹할 값이 없다. 그래도 쿠키·토큰을
            # 넣지 않는다는 규율은 그대로 지킨다.
            request_meta=meta,
            schema_fingerprint=parser.schema_fingerprint(html),
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

        명부는 금리 행을 만들지 않는다. 구조가 그대로인지만 확인한다 —
        `parse_outlet_list`가 머리글이 바뀌면 `SchemaChangedError`를 던진다.
        """
        html = artifact.content.decode("utf-8", "replace")
        meta: dict[str, Any] = artifact.request_meta
        if meta.get("kind") == "list":
            count = len(parser.parse_outlet_list(html))
            return [], ([] if count else ["명부가 비어 있다"])

        outlet = NhOutlet(**meta["outlet"])
        rows, warnings = parser.parse_detail(
            html,
            outlet=outlet,
            product_type=ProductType(meta["product_type"]),
            as_of=date.fromisoformat(meta["as_of"]),
            ejoy_options=meta.get("ejoy_options"),
        )
        return rows, [*meta.get("ejoy_warnings", []), *warnings]
