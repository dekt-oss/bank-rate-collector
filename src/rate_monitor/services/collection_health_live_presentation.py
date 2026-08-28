"""GitHub Actions의 현재 운영상태를 정적 수집 신호등에 합성한다.

공개 HTML의 기본 신호는 마지막으로 성공적으로 발행된 DB snapshot에서 온다.
그 값은 live API를 읽지 못할 때의 fallback이다. API 조회가 성공하면 상단 배지는
과거 snapshot보다 **현재 수집/복구 상태**를 우선한다.

현재 신호 계약:
- 정상 완료: green
- 정상 시각 안의 수집 진행: blue
- 정시 수집을 놓쳤지만 현재 수집/복구 중: yellow
- 정시 수집을 놓쳤거나 실패했고 현재 수집도 없음: red

수집/DB/R2 쓰기 경로에는 관여하지 않는다.
"""

from __future__ import annotations

MARKER = 'id="collection-health-live-signal-script"'

LIVE_HEALTH_SIGNAL_SCRIPT = r"""
<script id="collection-health-live-signal-script">
(() => {
  const endpoint = "api/health";
  const labels = {
    green: "정상",
    blue: "진행 중",
    yellow: "지연·수집 중",
    red: "미수집·실패",
    gray: "확인 불가",
  };
  let baselineSignal = null;
  let baselineLabel = null;
  let baselineTitle = null;

  const signalFor = (state) => {
    if (!state) return null;
    if (state.status === "breached" || state.status === "degraded") return "red";
    if (state.status === "warning") return "yellow";
    if (state.status === "pending") return "blue";
    if (state.status === "normal") return "green";
    if (state.status === "unknown") return "gray";
    return null;
  };

  const currentSignal = (dot) => (
    ["red", "yellow", "blue", "green", "gray"].find((value) => dot.classList.contains(value))
    || "gray"
  );

  const restoreBaseline = () => {
    const dot = document.getElementById("health-head-dot");
    const label = document.getElementById("health-head-label");
    const button = document.getElementById("health-open");
    if (!dot || !label || !button || !baselineSignal) return;
    dot.className = `health-dot ${baselineSignal}`;
    label.textContent = baselineLabel;
    button.title = baselineTitle;
  };

  const apply = (state) => {
    const dot = document.getElementById("health-head-dot");
    const label = document.getElementById("health-head-label");
    const button = document.getElementById("health-open");
    const live = signalFor(state);
    if (!dot || !label || !button || !live) return;

    // API가 정상 응답하면 current operational signal이 authoritative다.
    // 어제 snapshot의 green/red가 현재 회복/실패 상태를 가리지 않게 한다.
    dot.className = `health-dot ${live}`;
    label.textContent = `수집 ${labels[live]}`;
    const reason = state.reason ? ` · ${state.reason}` : "";
    button.title = `실시간 수집 상태: ${labels[live]}${reason}`;
  };

  const refresh = async () => {
    try {
      const response = await fetch(endpoint, { cache: "no-store" });
      const body = await response.json();
      if (response.ok && body && body.ok) {
        apply(body.signal || body.sla);
        return;
      }
      restoreBaseline();
    } catch {
      // live API가 실패하면 마지막 발행본의 정적 health를 fallback으로 유지한다.
      restoreBaseline();
    }
  };

  const start = () => {
    const dot = document.getElementById("health-head-dot");
    const label = document.getElementById("health-head-label");
    const button = document.getElementById("health-open");
    if (!dot || !label || !button) return;
    baselineSignal = currentSignal(dot);
    baselineLabel = label.textContent;
    baselineTitle = button.title;
    refresh();
    button.addEventListener("click", refresh);
    document.getElementById("health-refresh")?.addEventListener("click", refresh);
    window.setInterval(refresh, 5 * 60 * 1000);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
</script>
""".strip()


def inject_collection_health_live_signal(html: str) -> str:
    """수집 상태 버튼이 있는 화면에 live current-state signal을 한 번만 붙인다."""
    if MARKER in html or 'id="health-head-dot"' not in html:
        return html
    if "</body>" not in html:
        raise ValueError("collection health live signal: </body> marker가 없다")
    return html.replace("</body>", LIVE_HEALTH_SIGNAL_SCRIPT + "\n</body>", 1)
