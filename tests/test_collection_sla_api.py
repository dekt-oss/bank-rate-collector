"""08:00 cycle SLA 경계값과 source 실패 결합을 실제 Node API로 검증한다."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEALTH_API = (ROOT / "web/api/health.js").as_uri()


def _node(script: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _sla(completed: str | None, now: str, source_state: dict | None = None) -> dict:
    completed_js = json.dumps(completed)
    source_state_js = json.dumps(source_state)
    script = f"""
      import {{ cycleSla }} from {json.dumps(HEALTH_API)};
      const run = {{ run_started_at: '2026-08-10T19:17:00Z' }};
      console.log(JSON.stringify(cycleSla(
        run,
        {completed_js},
        new Date({json.dumps(now)}),
        {source_state_js},
      )));
    """
    return _node(script)


def test_publish_before_0730_is_normal() -> None:
    result = _sla("2026-08-10T22:20:00Z", "2026-08-10T22:20:00Z")
    assert result["cycle_date_kst"] == "2026-08-11"
    assert result["status"] == "normal"
    assert result["timing_status"] == "normal"
    assert result["normal_target_at"].endswith("T07:30:00+09:00")
    assert result["sla_deadline_at"].endswith("T08:00:00+09:00")


def test_publish_between_0730_and_0800_is_warning() -> None:
    result = _sla("2026-08-10T22:45:00Z", "2026-08-10T22:45:00Z")
    assert result["status"] == "warning"
    assert result["timing_status"] == "warning"


def test_publish_after_0800_is_breached() -> None:
    result = _sla("2026-08-10T23:05:00Z", "2026-08-10T23:05:00Z")
    assert result["status"] == "breached"
    assert result["timing_status"] == "breached"


def test_unfinished_cycle_moves_pending_warning_breached() -> None:
    assert _sla(None, "2026-08-10T22:00:00Z")["status"] == "pending"
    assert _sla(None, "2026-08-10T22:45:00Z")["status"] == "warning"
    assert _sla(None, "2026-08-10T23:05:00Z")["status"] == "breached"


def test_on_time_publish_with_failed_source_is_degraded_not_normal() -> None:
    source_state = {
        "status": "failed",
        "failed_sources": ["nh_local"],
        "missing_sources": [],
    }
    result = _sla(
        "2026-08-10T22:20:00Z",
        "2026-08-10T22:20:00Z",
        source_state,
    )
    assert result["timing_status"] == "normal"
    assert result["source_status"] == "failed"
    assert result["status"] == "degraded"
    assert result["failed_sources"] == ["nh_local"]


def test_late_publish_stays_breached_even_if_source_also_failed() -> None:
    source_state = {
        "status": "failed",
        "failed_sources": ["nh_local"],
        "missing_sources": [],
    }
    result = _sla(
        "2026-08-10T23:05:00Z",
        "2026-08-10T23:05:00Z",
        source_state,
    )
    assert result["timing_status"] == "breached"
    assert result["source_status"] == "failed"
    assert result["status"] == "breached"


def test_health_handler_combines_core_failure_with_kfcc_publish() -> None:
    """KFCC가 제시간에 발행돼도 core의 NH 실패를 전체 정상으로 숨기지 않는다."""
    script = f"""
      import handler from {json.dumps(HEALTH_API)};
      process.env.GITHUB_DISPATCH_TOKEN = 'test-token';
      process.env.GITHUB_REPOSITORY = 'dekt-oss/bank-rate-collector';

      const runs = [
        {{
          id: 202,
          run_number: 202,
          event: 'schedule',
          status: 'completed',
          conclusion: 'success',
          run_started_at: '2026-08-10T19:20:00Z',
          created_at: '2026-08-10T19:17:00Z',
          updated_at: '2026-08-10T22:20:00Z',
          html_url: 'https://example.test/kfcc',
        }},
        {{
          id: 201,
          run_number: 201,
          event: 'schedule',
          status: 'completed',
          conclusion: 'success',
          run_started_at: '2026-08-10T15:20:00Z',
          created_at: '2026-08-10T15:17:00Z',
          updated_at: '2026-08-10T19:10:00Z',
          html_url: 'https://example.test/core',
        }},
      ];
      const step = (name, conclusion, completedAt = '2026-08-10T19:00:00Z') => ({{
        name,
        status: 'completed',
        conclusion,
        started_at: '2026-08-10T18:59:00Z',
        completed_at: completedAt,
      }});
      const coreSteps = [
        step('Collect finlife savings bank', 'success'),
        step('Collect finlife bank', 'success'),
        step('Collect BOK base rate', 'success'),
        step('Collect FSB', 'success'),
        step('Collect CU', 'success'),
        step('Collect NH local', 'failure'),
        step('Collect KFCC', 'skipped'),
      ];
      const kfccSteps = [
        step('Collect finlife savings bank', 'skipped'),
        step('Collect finlife bank', 'skipped'),
        step('Collect BOK base rate', 'skipped'),
        step('Collect FSB', 'skipped'),
        step('Collect CU', 'skipped'),
        step('Collect NH local', 'skipped'),
        step('Collect KFCC', 'success'),
        step('Publish to rate-data branch', 'success', '2026-08-10T22:20:00Z'),
      ];

      globalThis.fetch = async (url) => {{
        const value = String(url);
        if (value.includes('/actions/workflows/collect.yml/runs?event=schedule&per_page=20')) {{
          return {{
            ok: true,
            status: 200,
            json: async () => ({{ workflow_runs: runs }}),
          }};
        }}
        if (value.includes('/actions/workflows/collect.yml/runs?per_page=30')) {{
          return {{
            ok: true,
            status: 200,
            json: async () => ({{ workflow_runs: runs }}),
          }};
        }}
        if (value.includes('/actions/runs/202/jobs?per_page=20')) {{
          return {{
            ok: true,
            status: 200,
            json: async () => ({{ jobs: [{{ steps: kfccSteps }}] }}),
          }};
        }}
        if (value.includes('/actions/runs/201/jobs?per_page=20')) {{
          return {{
            ok: true,
            status: 200,
            json: async () => ({{ jobs: [{{ steps: coreSteps }}] }}),
          }};
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
    assert result["timing_status"] == "normal"
    assert result["source_status"] == "failed"
    assert result["status"] == "degraded"
    assert result["failed_sources"] == ["nh_local"]
    assert result["missing_sources"] == []


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
