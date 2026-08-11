from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


# 1) Health API: isolate schedule evidence from push-heavy recent-run window and
# distinguish GitHub jobs API evidence failure from an actual source/SLA failure.
path = Path("web/api/health.js")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '  const sourceStatus = sourceState?.status || "unknown";\n'
    '  let status = timingStatus;\n'
    '  if (timingStatus !== "breached" && ["failed", "incomplete"].includes(sourceStatus)) {\n'
    '    status = "degraded";\n'
    '  }',
    '  const sourceStatus = sourceState?.status || "not_checked";\n'
    '  let status = timingStatus;\n'
    '  if (sourceState && sourceStatus === "unknown") {\n'
    '    status = "unknown";\n'
    '  } else if (\n'
    '    timingStatus !== "breached" && ["failed", "incomplete"].includes(sourceStatus)\n'
    '  ) {\n'
    '    status = "degraded";\n'
    '  }',
    "cycleSla unknown evidence",
)
text = replace_once(
    text,
    '  if (!run) return { sourceSteps, pipelineSteps };',
    '  if (!run) return { sourceSteps, pipelineSteps, evidenceAvailable: true };',
    "loadRunSteps no run",
)
text = replace_once(
    text,
    '  if (!jobsRes.ok) return { sourceSteps, pipelineSteps };',
    '  if (!jobsRes.ok) return { sourceSteps, pipelineSteps, evidenceAvailable: false };',
    "loadRunSteps jobs failure",
)
text = replace_once(
    text,
    '  return { sourceSteps, pipelineSteps };\n};\n\nconst cycleSourceState',
    '  return { sourceSteps, pipelineSteps, evidenceAvailable: true };\n};\n\nconst cycleSourceState',
    "loadRunSteps success",
)
text = replace_once(
    text,
    'const cycleSourceState = (cycleDetails, publishCompletedAt) => {\n'
    '  const sourceSteps = {};',
    'const cycleSourceState = (cycleDetails, publishCompletedAt) => {\n'
    '  if (cycleDetails.some((detail) => detail.evidenceAvailable === false)) {\n'
    '    return {\n'
    '      status: "unknown",\n'
    '      failed_sources: [],\n'
    '      missing_sources: [],\n'
    '    };\n'
    '  }\n\n'
    '  const sourceSteps = {};',
    "cycleSourceState evidence gate",
)
text = replace_once(
    text,
    '  const runsRes = await gh(token, `/repos/${slug}/actions/workflows/${WORKFLOW}/runs?per_page=30`);\n'
    '  if (!runsRes.ok) {\n'
    '    return json(res, 502, { ok: false, error: `GitHub 실행 상태를 읽지 못했습니다 (${runsRes.status}).` });\n'
    '  }\n'
    '  const runs = (await runsRes.json()).workflow_runs || [];\n'
    '  const collections = runs.filter((run) => run.event !== "push");\n'
    '  const activeCollection = collections.find((run) => ACTIVE.has(run.status)) || null;\n'
    '  const activePublish = runs.find((run) => run.event === "push" && ACTIVE.has(run.status)) || null;\n'
    '  const latestCollection = collections[0] || null;\n'
    '  const scheduledRuns = collections.filter((run) => run.event === "schedule");\n'
    '  const latestScheduled = scheduledRuns[0] || null;',
    '  const [runsRes, scheduledRunsRes] = await Promise.all([\n'
    '    gh(token, `/repos/${slug}/actions/workflows/${WORKFLOW}/runs?per_page=30`),\n'
    '    gh(token, `/repos/${slug}/actions/workflows/${WORKFLOW}/runs?event=schedule&per_page=20`),\n'
    '  ]);\n'
    '  if (!runsRes.ok) {\n'
    '    return json(res, 502, { ok: false, error: `GitHub 실행 상태를 읽지 못했습니다 (${runsRes.status}).` });\n'
    '  }\n'
    '  if (!scheduledRunsRes.ok) {\n'
    '    return json(res, 502, {\n'
    '      ok: false,\n'
    '      error: `GitHub 정기 수집 이력을 읽지 못했습니다 (${scheduledRunsRes.status}).`,\n'
    '    });\n'
    '  }\n'
    '  const runs = (await runsRes.json()).workflow_runs || [];\n'
    '  const scheduledRuns = (await scheduledRunsRes.json()).workflow_runs || [];\n'
    '  const collections = runs.filter((run) => run.event !== "push");\n'
    '  const activeCollection = collections.find((run) => ACTIVE.has(run.status)) || null;\n'
    '  const activePublish = runs.find((run) => run.event === "push" && ACTIVE.has(run.status)) || null;\n'
    '  const latestCollection = collections[0] || null;\n'
    '  const latestScheduled = scheduledRuns[0] || null;',
    "separate schedule query",
)
path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


# 2) Source freshness: do not relax core sources from 07:00 to 08:00 merely because
# the full-cycle hard deadline is 08:00. Only KFCC is tightened 09:00 -> 08:00.
path = Path("src/rate_monitor/services/source_health_service.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '# 평일 정기 cycle의 hard deadline은 08:00 KST다. core/KFCC 시작시각은\n'
    '# 서로 다르지만 사용자가 요구하는 최신성 계약은 "같은 날 08시까지 성공"이다.\n'
    '# 개별 source의 run health와 전체 cycle SLA는 별도로 표시한다.\n'
    'EXPECTED_BY_HOUR_KST: dict[str, int] = {}\n'
    'DEFAULT_EXPECTED_BY_HOUR_KST = 8',
    '# 개별 source freshness와 전체 cycle SLA를 분리한다. core source의 기존\n'
    '# 07:00 freshness cutoff는 느슨하게 만들지 않고, KFCC만 09:00 -> 08:00으로\n'
    '# 조인다. 전체 cycle의 hard deadline 08:00은 /api/health에서 별도 계산한다.\n'
    'EXPECTED_BY_HOUR_KST: dict[str, int] = {\n'
    '    "kfcc": 8,\n'
    '}\n'
    'DEFAULT_EXPECTED_BY_HOUR_KST = 7',
    "source freshness cutoffs",
)
path.write_text(text, encoding="utf-8")


# 3) Freshness regression tests: preserve 07:00 core cutoff and 08:00 KFCC cutoff.
path = Path("tests/test_collection_health.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'from datetime import datetime',
    'from datetime import date, datetime',
    "health test date import",
)
text = replace_once(
    text,
    '    build_collection_health,\n)',
    '    build_collection_health,\n    expected_collection_date,\n)',
    "health test expected_collection_date import",
)
text = replace_once(
    text,
    '    # 월요일 07:45 KST: hard cutoff(08시) 전이므로 금요일이 기대일 → 정상\n'
    '    before = _health(path, datetime(2026, 8, 10, 7, 45, tzinfo=KST))["sources"][0]\n'
    '    assert before["freshness"]["signal"] == "green"\n'
    '    # 월요일 08:05: 월요일 수집 1회를 놓침 → yellow\n'
    '    after = _health(path, datetime(2026, 8, 10, 8, 5, tzinfo=KST))["sources"][0]\n'
    '    assert after["freshness"]["signal"] == "yellow"\n'
    '    # 화요일 08:05까지 못 받음 → 2회 지연 red\n'
    '    late = _health(path, datetime(2026, 8, 11, 8, 5, tzinfo=KST))["sources"][0]',
    '    # core source의 기존 07:00 cutoff는 유지한다.\n'
    '    before = _health(path, datetime(2026, 8, 10, 6, 45, tzinfo=KST))["sources"][0]\n'
    '    assert before["freshness"]["signal"] == "green"\n'
    '    # 월요일 07:05: 월요일 수집 1회를 놓침 → yellow\n'
    '    after = _health(path, datetime(2026, 8, 10, 7, 5, tzinfo=KST))["sources"][0]\n'
    '    assert after["freshness"]["signal"] == "yellow"\n'
    '    # 화요일 07:05까지 못 받음 → 2회 지연 red\n'
    '    late = _health(path, datetime(2026, 8, 11, 7, 5, tzinfo=KST))["sources"][0]',
    "core freshness boundary",
)
anchor = '\n\ndef test_disabled_source_is_gray(tmp_path) -> None:\n'
addition = '''\n\ndef test_kfcc_freshness_cutoff_is_eight_but_core_stays_seven() -> None:\n    friday = date(2026, 8, 7)\n    monday = date(2026, 8, 10)\n    assert expected_collection_date(\n        "nh_local", datetime(2026, 8, 10, 6, 59, tzinfo=KST)\n    ) == friday\n    assert expected_collection_date(\n        "nh_local", datetime(2026, 8, 10, 7, 0, tzinfo=KST)\n    ) == monday\n    assert expected_collection_date(\n        "kfcc", datetime(2026, 8, 10, 7, 59, tzinfo=KST)\n    ) == friday\n    assert expected_collection_date(\n        "kfcc", datetime(2026, 8, 10, 8, 0, tzinfo=KST)\n    ) == monday\n'''
text = replace_once(text, anchor, addition + anchor, "kfcc freshness regression")
path.write_text(text, encoding="utf-8")


# 4) SLA handler tests: existing mock must answer the separate schedule query.
path = Path("tests/test_collection_sla_api.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "        if (value.includes('/actions/workflows/collect.yml/runs?per_page=30')) {{\n"
    "          return {{\n"
    "            ok: true,\n"
    "            status: 200,\n"
    "            json: async () => ({{ workflow_runs: runs }}),\n"
    "          }};\n"
    "        }}",
    "        if (value.includes('/actions/workflows/collect.yml/runs?event=schedule&per_page=20')) {{\n"
    "          return {{\n"
    "            ok: true,\n"
    "            status: 200,\n"
    "            json: async () => ({{ workflow_runs: runs }}),\n"
    "          }};\n"
    "        }}\n"
    "        if (value.includes('/actions/workflows/collect.yml/runs?per_page=30')) {{\n"
    "          return {{\n"
    "            ok: true,\n"
    "            status: 200,\n"
    "            json: async () => ({{ workflow_runs: runs }}),\n"
    "          }};\n"
    "        }}",
    "existing handler schedule mock",
)
append = r'''


def test_schedule_history_is_not_lost_when_recent_window_is_push_heavy() -> None:
    """일반 30-run 창에서 core가 밀려도 schedule 전용 조회로 같은 cycle을 복원한다."""
    script = f"""
      import handler from {json.dumps(HEALTH_API)};
      process.env.GITHUB_DISPATCH_TOKEN = 'test-token';
      process.env.GITHUB_REPOSITORY = 'dekt-oss/bank-rate-collector';

      const kfccRun = {{
        id: 302, run_number: 302, event: 'schedule', status: 'completed', conclusion: 'success',
        run_started_at: '2026-08-10T19:20:00Z', created_at: '2026-08-10T19:17:00Z',
        updated_at: '2026-08-10T22:20:00Z', html_url: 'https://example.test/kfcc',
      }};
      const coreRun = {{
        id: 301, run_number: 301, event: 'schedule', status: 'completed', conclusion: 'success',
        run_started_at: '2026-08-10T15:20:00Z', created_at: '2026-08-10T15:17:00Z',
        updated_at: '2026-08-10T19:10:00Z', html_url: 'https://example.test/core',
      }};
      const pushes = Array.from({{ length: 29 }}, (_, index) => ({{
        id: 400 + index, run_number: 400 + index, event: 'push', status: 'completed',
        conclusion: 'success', run_started_at: '2026-08-11T00:00:00Z',
        created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:01:00Z',
        html_url: 'https://example.test/push',
      }}));
      const recentRuns = [kfccRun, ...pushes];
      const scheduledRuns = [kfccRun, coreRun];
      const step = (name, completedAt = '2026-08-10T19:00:00Z') => ({{
        name, status: 'completed', conclusion: 'success',
        started_at: '2026-08-10T18:59:00Z', completed_at: completedAt,
      }});
      const coreSteps = [
        step('Collect finlife savings bank'), step('Collect finlife bank'),
        step('Collect BOK base rate'), step('Collect FSB'), step('Collect CU'),
        step('Collect NH local'),
        {{ ...step('Collect KFCC'), conclusion: 'skipped' }},
      ];
      const kfccSteps = [
        {{ ...step('Collect finlife savings bank'), conclusion: 'skipped' }},
        {{ ...step('Collect finlife bank'), conclusion: 'skipped' }},
        {{ ...step('Collect BOK base rate'), conclusion: 'skipped' }},
        {{ ...step('Collect FSB'), conclusion: 'skipped' }},
        {{ ...step('Collect CU'), conclusion: 'skipped' }},
        {{ ...step('Collect NH local'), conclusion: 'skipped' }},
        step('Collect KFCC'),
        step('Publish to rate-data branch', '2026-08-10T22:20:00Z'),
      ];

      globalThis.fetch = async (url) => {{
        const value = String(url);
        if (value.includes('/runs?event=schedule&per_page=20')) {{
          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: scheduledRuns }}) }};
        }}
        if (value.includes('/runs?per_page=30')) {{
          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: recentRuns }}) }};
        }}
        if (value.includes('/actions/runs/302/jobs?per_page=20')) {{
          return {{ ok: true, status: 200, json: async () => ({{ jobs: [{{ steps: kfccSteps }}] }}) }};
        }}
        if (value.includes('/actions/runs/301/jobs?per_page=20')) {{
          return {{ ok: true, status: 200, json: async () => ({{ jobs: [{{ steps: coreSteps }}] }}) }};
        }}
        throw new Error(`unexpected URL: ${{value}}`);
      }};

      let payload = null;
      const res = {{
        setHeader() {{}},
        status(code) {{ this.statusCode = code; return this; }},
        send(body) {{ payload = JSON.parse(body); }},
      }};
      await handler({{ method: 'GET' }}, res);
      console.log(JSON.stringify(payload.sla));
    """
    result = _node(script)
    assert result["cycle_date_kst"] == "2026-08-11"
    assert result["source_status"] == "healthy"
    assert result["status"] == "normal"
    assert result["failed_sources"] == []
    assert result["missing_sources"] == []


def test_jobs_api_failure_is_unknown_not_a_false_sla_breach() -> None:
    """GitHub jobs API 장애는 source 실패나 08:00 위반의 증거가 아니다."""
    script = f"""
      import handler from {json.dumps(HEALTH_API)};
      process.env.GITHUB_DISPATCH_TOKEN = 'test-token';
      process.env.GITHUB_REPOSITORY = 'dekt-oss/bank-rate-collector';
      const run = {{
        id: 501, run_number: 501, event: 'schedule', status: 'completed', conclusion: 'success',
        run_started_at: '2026-08-10T19:20:00Z', created_at: '2026-08-10T19:17:00Z',
        updated_at: '2026-08-10T22:20:00Z', html_url: 'https://example.test/run',
      }};
      globalThis.fetch = async (url) => {{
        const value = String(url);
        if (value.includes('/runs?event=schedule&per_page=20')) {{
          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: [run] }}) }};
        }}
        if (value.includes('/runs?per_page=30')) {{
          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: [run] }}) }};
        }}
        if (value.includes('/actions/runs/501/jobs?per_page=20')) {{
          return {{ ok: false, status: 502, json: async () => ({{}}) }};
        }}
        throw new Error(`unexpected URL: ${{value}}`);
      }};
      let payload = null;
      const res = {{
        setHeader() {{}},
        status(code) {{ this.statusCode = code; return this; }},
        send(body) {{ payload = JSON.parse(body); }},
      }};
      await handler({{ method: 'GET' }}, res);
      console.log(JSON.stringify(payload.sla));
    """
    result = _node(script)
    assert result["source_status"] == "unknown"
    assert result["status"] == "unknown"
    assert result["failed_sources"] == []
'''
if "def test_schedule_history_is_not_lost_when_recent_window_is_push_heavy" in text:
    raise SystemExit("SLA follow-up tests already present")
path.write_text(text.rstrip() + append + "\n", encoding="utf-8")


# 5) UI: unknown evidence is neutral/explicit, never a red SLA failure.
path = Path("web/templates/site.html")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    const sig = (sla.status === "breached" || sla.status === "degraded") ? "red"\n'
    '      : (sla.status === "normal" ? "green" : (sla.status === "warning" ? "yellow" : "blue"));\n'
    '    const label = sla.status === "normal" ? "정상"\n'
    '      : (sla.status === "warning" ? "마감 임박"\n'
    '        : (sla.status === "breached" ? "08:00 초과"\n'
    '          : (sla.status === "degraded" ? "일부 원천 실패" : "진행 중")));',
    '    const sig = (sla.status === "breached" || sla.status === "degraded") ? "red"\n'
    '      : (sla.status === "normal" ? "green"\n'
    '        : (sla.status === "warning" ? "yellow" : (sla.status === "unknown" ? "gray" : "blue")));\n'
    '    const label = sla.status === "normal" ? "정상"\n'
    '      : (sla.status === "warning" ? "마감 임박"\n'
    '        : (sla.status === "breached" ? "08:00 초과"\n'
    '          : (sla.status === "degraded" ? "일부 원천 실패"\n'
    '            : (sla.status === "unknown" ? "판정 불가" : "진행 중"))));',
    "SLA unknown UI",
)
path.write_text(text, encoding="utf-8")


# 6) Static UI contract follows the new query/evidence semantics.
path = Path("tests/test_collection_health_ui.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    assert \'collections.filter((run) => run.event === "schedule")\' in API',
    '    assert "runs?event=schedule&per_page=20" in API',
    "health UI schedule query assertion",
)
text = replace_once(
    text,
    '    assert "일부 원천 실패" in SITE',
    '    assert "일부 원천 실패" in SITE\n'
    '    assert \'status = "unknown"\' in API\n'
    '    assert "판정 불가" in SITE',
    "health UI unknown assertion",
)
path.write_text(text, encoding="utf-8")
