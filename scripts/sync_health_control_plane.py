"""rate-data의 health API와 상단 신호 스크립트만 최신 main 계약으로 맞춘다.

이 스크립트는 DB/R2/금리 데이터 파일을 읽거나 쓰지 않는다. 수집 writer가 오래
걸리거나 실패해도 health control-plane은 독립적으로 배포할 수 있어야 한다.
"""

from __future__ import annotations

import argparse
import runpy
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESENTATION = ROOT / "src/rate_monitor/services/collection_health_live_presentation.py"
HEALTH_API = ROOT / "web/api/health.js"
MARKER = 'id="collection-health-live-signal-script"'
SCRIPT_CLOSE = "</script>"


def _live_script() -> str:
    namespace = runpy.run_path(str(PRESENTATION))
    value = namespace.get("LIVE_HEALTH_SIGNAL_SCRIPT")
    if not isinstance(value, str) or MARKER not in value:
        raise RuntimeError("live health signal script 계약을 읽지 못했다")
    return value


def sync_html_text(html: str, live_script: str) -> tuple[str, bool]:
    """기존 health script를 교체하거나, 아직 없으면 body 끝에 주입한다."""
    marker_at = html.find(MARKER)
    if marker_at >= 0:
        script_start = html.rfind("<script", 0, marker_at)
        script_end = html.find(SCRIPT_CLOSE, marker_at)
        if script_start < 0 or script_end < 0:
            raise RuntimeError("기존 live health script 경계를 찾지 못했다")
        script_end += len(SCRIPT_CLOSE)
        updated = html[:script_start] + live_script + html[script_end:]
        return updated, updated != html

    if 'id="health-head-dot"' not in html:
        return html, False
    if "</body>" not in html:
        raise RuntimeError("health badge가 있지만 </body>가 없다")
    return html.replace("</body>", live_script + "\n</body>", 1), True


def sync_control_plane(deploy_root: Path) -> list[str]:
    """배포 tree에서 control-plane 파일만 갱신하고 변경 경로를 반환한다."""
    if not deploy_root.exists():
        raise FileNotFoundError(f"배포 root가 없다: {deploy_root}")

    changed: list[str] = []
    api_target = deploy_root / "api/health.js"
    api_target.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = HEALTH_API.read_bytes()
    target_bytes = api_target.read_bytes() if api_target.exists() else None
    if target_bytes != source_bytes:
        shutil.copyfile(HEALTH_API, api_target)
        changed.append("api/health.js")

    live_script = _live_script()
    for relative in ("site-public/index.html", "site-public/strategy.html"):
        path = deploy_root / relative
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        updated, did_change = sync_html_text(original, live_script)
        if did_change:
            path.write_text(updated, encoding="utf-8")
            changed.append(relative)

    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy-root", type=Path, required=True)
    args = parser.parse_args()
    changed = sync_control_plane(args.deploy_root)
    if changed:
        print("health control-plane updated:", ", ".join(changed))
    else:
        print("health control-plane already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
