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
전국이면 9,743회(약 2시간 43분)다. 기본 범위를 부산으로 두는 이유이고,
config가 그 값을 갖고 있다.

차단 우회는 하지 않는다 (v3 §0.2, §16.1). 차단이 보이면 즉시 멈춘다.
"""

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import yaml

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.nh_local import parser
from rate_monitor.collectors.nh_local.parser import NhOutlet
from rate_monitor.domain.enums import (
    CollectionMode,
    ProductType,
    Sector,
    SourceRole,
    TrustLevel,
)
from rate_monitor.domain.schemas import CollectionRequest, ParsedRateRow, RawArtifactData
from rate_monitor.domain.timeutil import now_kst

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

    def __init__(self, regions_path: Path | None = None) -> None:
        self._regions_path = regions_path or REGIONS_PATH

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

    async def _get(
        self, client: httpx.AsyncClient, screen: str, params: dict[str, str]
    ) -> bytes:
        url = f"{BASE_URL}/servlet/{screen}.view"
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
        prefixes = self._load_prefixes(request)
        products = tuple(request.options.get("products") or DEFAULT_PRODUCTS)
        # 조회일이 곧 기준일이다. 원천이 별도 공시일을 주지 않는다 (정찰 §0.2).
        as_of = now_kst().date().isoformat()

        artifacts: list[RawArtifactData] = []
        # raw_artifacts에 UNIQUE(run_id, sha256)이 있다. 바이트가 같은 응답이
        # 둘이면 저장에서 IntegrityError가 난다.
        seen_bodies: set[bytes] = set()
        requests_made = 0

        timeout = httpx.Timeout(
            connect=CONNECT_TIMEOUT, read=READ_TIMEOUT,
            write=READ_TIMEOUT, pool=CONNECT_TIMEOUT,
        )
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            # 1단계: 전국 명부. 페이지네이션이 없다.
            body = await self._get(client, LIST_SCREEN, {})
            requests_made += 1
            seen_bodies.add(body)
            artifacts.append(
                self._artifact(
                    body,
                    filename="outlet_list.html",
                    meta={"kind": "list", "screen": LIST_SCREEN},
                )
            )
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

            outlets = parser.outlets_in(
                parser.parse_outlet_list(body.decode("utf-8", "replace")), prefixes
            )
            if not outlets:
                raise SourceBlockedError(
                    f"명부에서 범위에 맞는 점포가 하나도 없다 (접두어 {prefixes})"
                )

            # 2단계: 점포·상품분류별 금리
            for outlet in outlets:
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
                    )
                    requests_made += 1
                    await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

                    if body in seen_bodies:
                        continue
                    seen_bodies.add(body)

                    artifacts.append(
                        self._artifact(
                            body,
                            filename=f"rate_{outlet.brc}_{screen}.html",
                            meta={
                                "kind": "rate",
                                "screen": screen,
                                "product_type": product.value,
                                "as_of": as_of,
                                # 금리 화면에도 점포명은 있지만 주소는 없다.
                                # 파서가 붙일 수 있게 명부 행을 실어 보낸다.
                                "outlet": outlet._asdict(),
                            },
                        )
                    )
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
        return parser.parse_detail(
            html,
            outlet=outlet,
            product_type=ProductType(meta["product_type"]),
            as_of=date.fromisoformat(meta["as_of"]),
        )
