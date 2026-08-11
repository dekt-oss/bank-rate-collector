from pathlib import Path

path = Path("web/templates/site.html")
text = path.read_text(encoding="utf-8")
old = '''  const slaLine = (sla) => {
    if (!sla) return "";
    const sig = sla.status === "normal" ? "green"
      : (sla.status === "warning" ? "yellow" : (sla.status === "breached" ? "red" : "blue"));
    const label = sla.status === "normal" ? "정상"
      : (sla.status === "warning" ? "마감 임박" : (sla.status === "breached" ? "08:00 초과" : "진행 중"));
    const done = sla.latest_publish_completed_at
      ? ` · 최종 발행 ${healthDate(sla.latest_publish_completed_at)}` : "";
    return `${healthDot(sig)} 08:00 SLA ${esc(label)} · 기준일 ${esc(sla.cycle_date_kst)}${done}`;
  };
'''
new = '''  const slaLine = (sla) => {
    if (!sla) return "";
    const sig = (sla.status === "breached" || sla.status === "degraded") ? "red"
      : (sla.status === "normal" ? "green" : (sla.status === "warning" ? "yellow" : "blue"));
    const label = sla.status === "normal" ? "정상"
      : (sla.status === "warning" ? "마감 임박"
        : (sla.status === "breached" ? "08:00 초과"
          : (sla.status === "degraded" ? "일부 원천 실패" : "진행 중")));
    const done = sla.latest_publish_completed_at
      ? ` · 최종 발행 ${healthDate(sla.latest_publish_completed_at)}` : "";
    const failed = (sla.failed_sources || []).length
      ? ` · 실패 ${(sla.failed_sources || []).length}개` : "";
    return `${healthDot(sig)} 08:00 SLA ${esc(label)} · 기준일 ${esc(sla.cycle_date_kst)}${done}${failed}`;
  };
'''
if text.count(old) != 1:
    raise SystemExit(f"expected one SLA line block, got {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
