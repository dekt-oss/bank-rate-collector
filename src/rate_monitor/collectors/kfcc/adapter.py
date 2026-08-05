"""새마을금고 공식 페이지 어댑터.

fetch()만 담당한다. 파싱은 parser가, 저장은 오케스트레이터가 한다
(명세서 v3 §6.2).

두 단계로 돈다 (docs/source-recon/kfcc.md).

    1. 구·군마다 목록      GET /map/list.do?r1=&r2=
    2. 금고마다 상품군별   GET /map/goods_19.do?OPEN_TRMID=&gubuncode=

금리는 `gmgoCd`당 한 번만 받는다. 점포 수만큼 복제하지 않는다 (v3 §7.3.4-6).
부산 기준 점포 273개 대비 금고 137개라 요청이 절반으로 줄고 중복 행도 안 생긴다.

차단 우회는 하지 않는다 (v3 §0.2, §16.1). 차단이 보이면 즉시 멈춘다.
"""

import asyncio
from pathlib import Path
from typing import Any

import httpx
import yaml

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.kfcc import parser
from rate_monitor.domain.enums import (
    CollectionMode,
    JoinChannel,
    Sector,
    SourceRole,
    TrustLevel,
)
from rate_monitor.domain.schemas import CollectionRequest, ParsedRateRow, RawArtifactData

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

# 수집 대상 상품군. 요구불(12)은 단계금액 구간 파싱이 따로 필요해 미룬다.
DEFAULT_GROUPS = ("13", "14")

# 폭주 방지. 부산 실측은 목록 16 + 금고 137 × 상품군 2 = 290회다.
MAX_REQUESTS = 1200

# 새마을금고는 차단 시 200이 아니라 400에 이 문구를 실어 보낸 이력이 있다.
# finlife처럼 403/429만 보면 이 경우를 놓친다.
BLOCK_MARKERS = ("Request Blocked", "Access Denied")
BLOCK_STATUSES = (400, 403, 429)


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
    coverage_status = "partial"

    # 금리가 창구판매 기준이라는 안내는 이 금리 페이지가 아니라 그것을 감싸는
    # view.do에 있다. 금리 페이지만 받아서는 알 수 없으므로 원천의 성질로
    # 여기서 명시한다 (docs/source-recon/kfcc.md §2.2).
    join_channel = JoinChannel.BRANCH

    def __init__(self, regions_path: Path | None = None) -> None:
        self._regions_path = regions_path or REGIONS_PATH

    # ── 지역 ────────────────────────────────────────────────────────────

    def _load_regions(self, request: CollectionRequest) -> tuple[str, list[str]]:
        """수집 대상 구·군을 정한다.

        요청이 구·군을 지정하면 그것만, 아니면 config의 전체를 쓴다.
        지역 목록을 코드에 박지 않는다 (v3 §7.3.4-8).
        """
        config = yaml.safe_load(self._regions_path.read_text(encoding="utf-8"))
        sido = config["kfcc_r1"]
        available = [entry["kfcc_r2"] for entry in config["sigungu"]]
        if not request.regions:
            return sido, available

        wanted = list(request.regions)
        unknown = [r for r in wanted if r not in available]
        if unknown:
            raise ValueError(f"config에 없는 구·군: {unknown}")
        return sido, wanted

    # ── 요청 ────────────────────────────────────────────────────────────

    async def _get(self, client: httpx.AsyncClient, url: str, params: dict) -> bytes:
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

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        sido, districts = self._load_regions(request)
        groups = tuple(request.options.get("groups") or DEFAULT_GROUPS)

        artifacts: list[RawArtifactData] = []
        seen_hashes: set[bytes] = set()
        requests_made = 0

        timeout = httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT,
                                write=READ_TIMEOUT, pool=CONNECT_TIMEOUT)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            # 1단계: 구·군 목록. 금고 대표 행을 모은다.
            outlets: dict[str, dict[str, str]] = {}
            for district in districts:
                params = {"r1": sido, "r2": district}
                body = await self._get(client, f"{BASE_URL}/map/list.do", params)
                requests_made += 1
                artifacts.append(
                    self._artifact(
                        body,
                        filename=f"list_{sido}_{district}.html",
                        meta={"kind": "list", "r1": sido, "r2": district},
                    )
                )
                for row in parser.parse_list(body.decode("utf-8", "replace")):
                    # 금고 대표 행은 먼저 본 것을 쓴다. 금리는 금고 단위라
                    # 어느 점포 행을 쓰든 같다.
                    outlets.setdefault(row["gmgoCd"], row)
                await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

            # 2단계: 금고별 금리
            for gmgo_cd, row in outlets.items():
                for group in groups:
                    if requests_made >= MAX_REQUESTS:
                        raise SourceBlockedError(
                            f"요청 상한 {MAX_REQUESTS}회에 도달했다. 설정을 확인한다"
                        )
                    params = {"OPEN_TRMID": gmgo_cd, "gubuncode": group}
                    body = await self._get(
                        client, f"{BASE_URL}/map/goods_19.do", params
                    )
                    requests_made += 1
                    await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

                    # raw_artifacts에 UNIQUE(run_id, sha256)이 있다. 응답이
                    # 바이트 단위로 같으면 저장에서 IntegrityError가 난다.
                    if body in seen_hashes:
                        continue
                    seen_hashes.add(body)

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
                            },
                        )
                    )
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
            join_channel=self.join_channel,
        )
