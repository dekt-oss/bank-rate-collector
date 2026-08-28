"""GitHub Actions 실시간 SLA를 정적 수집 신호등에 합성한다.

공개 HTML의 기본 신호는 마지막으로 성공적으로 발행된 DB snapshot에서 온다.
그 값은 fallback으로 계속 유효하지만, 다음 scheduled cycle이 늦거나 실패해도
새 publish가 없으면 스스로 바뀔 수 없다. 이 presentation은 read-only
``/api/health``를 페이지 로드 시 확인해 **더 나쁜 실시간 신호만** 상단 배지에
덮어쓴다. 수집/DB/R2 쓰기 경로에는 관여하지 않는다.
"""

from __future__ import annotations

MARKER = 'id="collection-health-live-signal-script"'

LIVE_HEALTH_SIGNAL_SCRIPT = r"""
<script id="collection-health-live-signal-script">
(() => {
  const endpoint = "api/health";
  const ranks = { gray: 0, green: 1, blue: 2, yellow: 3, red: 4 };
  const labels = {
    green: "정상",
    blue: "진행 중",
    yellow: "확인 필요",
    red: "실패·지연",
    gray: "대상 아님",
  };
  let baselineSignal = null;
  let baselineLabel = null;
  let baselineTitle = null;

  const signalFor = (sla) => {
    if (!sla) return null;
    if (sla.status === "breached" || sla.status === "degraded") return "red";
    if (sla.status === "warning") return "yellow";
    if (sla.status === "pending") return "blue";
    if (sla.status === "normal") return "green";
    return null;
  };

  const currentSignal = (dot) => (
    ["red", "yellow", "blue", "green", "gray"].find((value) => dot.classList.contains(value))
    || "gray"
  );

  const apply = (sla) => {
    const dot = document.getElementById("health-head-dot");
    const label = document.getElementById("health-head-label");
    const button = document.getElementById("health-open");
    const live = signalFor(sla);
    if (!dot || !label || !button || !live || !baselineSignal) return;

    const useLive = (ranks[live] || 0) > (ranks[baselineSignal] || 0);
    const signal = useLive ? live : baselineSignal;
    dot.className = `health-dot ${signal}`;
    if (!useLive) {
      label.textContent = baselineLabel;
      button.title = baselineTitle;
      return;
    }

    label.textContent = `수집 ${labels[live]}`;
    const schedule = sla.schedule_status && sla.schedule_status !== "normal"
      ? ` · 정기 실행 ${sla.schedule_status}`
      : "";
    button.title = `실시간 수집 상태: ${labels[live]}${schedule}`;
  };

  const refresh = async () => {
    try {
      const response = await fetch(endpoint, { cache: "no-store" });
      const body = await response.json();
      if (response.ok && body && body.ok) apply(body.sla);
    } catch {
      // live API가 실패하면 마지막 발행본의 정적 health를 fallback으로 유지한다.
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
    """수집 상태 버튼이 있는 화면에 live SLA override를 한 번만 붙인다."""
    if MARKER in html or 'id="health-head-dot"' not in html:
        return html
    if "</body>" not in html:
        raise ValueError("collection health live signal: </body> marker가 없다")
    return html.replace("</body>", LIVE_HEALTH_SIGNAL_SCRIPT + "\n</body>", 1)
