"""R2 버킷 용량 조회. **읽기만 한다.**

버킷에 무엇이 얼마나 쌓였는지 폴더(계열)별로 묶어 본다. 보관 정책을
정하려면 먼저 숫자가 있어야 하는데, R2 자격증명이 GitHub에만 있어 로컬에서는
볼 수 없다. 그래서 워크플로우에서 이 조회를 돌린다.

계열을 나누는 기준은 키 구조다. 같은 계열 안에서는 "단위"(날짜·실행)별로
묶어, 하루에 얼마씩 늘어나는지를 볼 수 있게 한다.

    state/snapshots/<KST시각>-<해시>.sqlite3.gz   → state/snapshots, 날짜
    checkpoints/v1/<source>/<cycle>/...           → checkpoints/v1/<source>, cycle
    raw-evidence/<category>/<run_id>/...          → raw-evidence/<category>, run_id
    intermediate/<UTC시각>/<category>/...          → intermediate/<category>, 날짜
    그 밖                                          → 첫 폴더, 단위 없음
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

# Cloudflare R2 Standard 요금 (2026-10 기준 공개 요금표).
# 무료 구간을 넘은 저장량에만 GB-월 단가가 붙는다. 다운로드(egress)는 무료다.
R2_FREE_STORAGE_GB = 10
R2_STORAGE_USD_PER_GB_MONTH = 0.015

GB = 1_000_000_000


class SizedObjectStore(Protocol):
    def list_sizes(self, prefix: str = "") -> list[tuple[str, int]]: ...


@dataclass
class FamilySummary:
    family: str
    objects: int = 0
    bytes: int = 0
    unit_bytes: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        units = sorted(self.unit_bytes)
        largest = sorted(self.unit_bytes.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {
            "family": self.family,
            "objects": self.objects,
            "bytes": self.bytes,
            "units": len(units),
            "first_unit": units[0] if units else None,
            "last_unit": units[-1] if units else None,
            "last_unit_bytes": self.unit_bytes[units[-1]] if units else None,
            "avg_bytes_per_unit": self.bytes // len(units) if units else None,
            "largest_units": [{"unit": u, "bytes": b} for u, b in largest],
        }


def classify(key: str) -> tuple[str, str | None]:
    """키 → (계열, 단위).

    >>> classify("state/snapshots/20261016T035605-522aa1b4.sqlite3.gz")
    ('state/snapshots', '20261016')
    >>> classify("state/current.json")
    ('state/(pointer)', None)
    >>> classify("checkpoints/v1/nh_local/2026-10-16/sessions/abc/chunks/000001-ff.tar.gz")
    ('checkpoints/v1/nh_local', '2026-10-16')
    >>> classify("raw-evidence/institution_funding/38719676210/a/b.json")
    ('raw-evidence/institution_funding', '38719676210')
    >>> classify("intermediate/20261016T010203Z/recon/x.json")
    ('intermediate/recon', '20261016')
    >>> classify("loose.bin")
    ('(root)', None)
    """
    parts = key.split("/")
    if parts[0] == "state":
        if len(parts) >= 3 and parts[1] == "snapshots":
            return "state/snapshots", parts[2][:8]
        if len(parts) == 2:
            return "state/(pointer)", None
        return f"state/{parts[1]}", None
    if parts[0] == "checkpoints" and len(parts) >= 4:
        return f"checkpoints/{parts[1]}/{parts[2]}", parts[3]
    if parts[0] == "raw-evidence" and len(parts) >= 4:
        return f"raw-evidence/{parts[1]}", parts[2]
    if parts[0] == "intermediate" and len(parts) >= 4:
        return f"intermediate/{parts[2]}", parts[1][:8]
    if len(parts) == 1:
        return "(root)", None
    return parts[0], None


def build_inventory(store: SizedObjectStore) -> dict[str, Any]:
    families: dict[str, FamilySummary] = {}
    for key, size in store.list_sizes(""):
        family, unit = classify(key)
        summary = families.setdefault(family, FamilySummary(family))
        summary.objects += 1
        summary.bytes += size
        if unit is not None:
            summary.unit_bytes[unit] = summary.unit_bytes.get(unit, 0) + size

    total = sum(f.bytes for f in families.values())
    by_top: dict[str, int] = defaultdict(int)
    for f in families.values():
        by_top[f.family.split("/", 1)[0]] += f.bytes

    billable_gb = max(0.0, total / GB - R2_FREE_STORAGE_GB)
    return {
        "total_objects": sum(f.objects for f in families.values()),
        "total_bytes": total,
        "by_top_level": dict(sorted(by_top.items(), key=lambda kv: kv[1], reverse=True)),
        "families": [
            f.to_dict() for f in sorted(families.values(), key=lambda f: f.bytes, reverse=True)
        ],
        "estimated_monthly_storage_usd": round(billable_gb * R2_STORAGE_USD_PER_GB_MONTH, 2),
        "pricing_assumption": {
            "free_storage_gb": R2_FREE_STORAGE_GB,
            "usd_per_gb_month": R2_STORAGE_USD_PER_GB_MONTH,
        },
    }


def _human(n: int | None) -> str:
    if n is None:
        return "-"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{value:,.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1000
    return f"{n} B"  # pragma: no cover


def render_inventory(report: dict[str, Any]) -> str:
    lines = [
        f"전체: {report['total_objects']:,}개, {_human(report['total_bytes'])}"
        f"  (예상 저장 요금 월 ${report['estimated_monthly_storage_usd']:.2f},"
        f" 무료 {report['pricing_assumption']['free_storage_gb']} GB 제외)",
        "",
        "최상위 폴더별:",
    ]
    for top, size in report["by_top_level"].items():
        lines.append(f"  {top:24s} {_human(size):>12s}")
    lines += ["", "계열별 (단위 = 날짜 또는 실행):"]
    for f in report["families"]:
        lines.append(
            f"  {f['family']:44s} {_human(f['bytes']):>12s}  {f['objects']:>7,}개"
            f"  단위 {f['units']:>4}개"
            f"  {f['first_unit'] or '-'} ~ {f['last_unit'] or '-'}"
            f"  단위당 평균 {_human(f['avg_bytes_per_unit'])}"
        )
    return "\n".join(lines)

