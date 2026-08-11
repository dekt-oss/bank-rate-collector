"""관리자 health가 same-workflow NH recovery 결과를 최종 source 결과로 사용한다."""

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


def test_recovery_success_supersedes_first_failure_but_skipped_recovery_does_not() -> None:
    script = f"""
      import handler from {json.dumps(HEALTH_API)};
      process.env.GITHUB_DISPATCH_TOKEN = 'test-token';
      process.env.GITHUB_REPOSITORY = 'dekt-oss/bank-rate-collector';

      const core = {{
        id: 701, run_number: 701, event: 'schedule', status: 'completed', conclusion: 'success',
        run_started_at: '2026-08-10T15:20:00Z', created_at: '2026-08-10T15:17:00Z',
        updated_at: '2026-08-10T19:10:00Z', html_url: 'https://example.test/core',
      }};
      const kfcc = {{
        id: 702, run_number: 702, event: 'schedule', status: 'completed', conclusion: 'success',
        run_started_at: '2026-08-10T19:20:00Z', created_at: '2026-08-10T19:17:00Z',
        updated_at: '2026-08-10T22:20:00Z', html_url: 'https://example.test/kfcc',
      }};
      const step = (name, conclusion, completedAt = '2026-08-10T19:00:00Z') => ({{
        name, status: 'completed', conclusion,
        started_at: '2026-08-10T18:59:00Z', completed_at: completedAt,
      }});
      const coreSteps = [
        step('Collect finlife savings bank', 'success'),
        step('Collect finlife bank', 'success'),
        step('Collect BOK base rate', 'success'),
        step('Collect FSB', 'success'),
        step('Collect CU', 'success'),
        step('Collect NH local', 'failure'),
        step('Decide NH recovery', 'success'),
        step('Recover NH local', 'success'),
        step('Collect KFCC', 'skipped'),
      ];
      const kfccSteps = [
        step('Collect NH local', 'skipped'),
        step('Recover NH local', 'skipped'),
        step('Collect KFCC', 'success'),
        step('Publish to rate-data branch', 'success', '2026-08-10T22:20:00Z'),
      ];

      globalThis.fetch = async (url) => {{
        const value = String(url);
        if (value.includes('/runs?event=schedule&per_page=20')) {{
          return {{
            ok: true, status: 200,
            json: async () => ({{ workflow_runs: [kfcc, core] }}),
          }};
        }}
        if (value.includes('/runs?per_page=30')) {{
          return {{
            ok: true, status: 200,
            json: async () => ({{ workflow_runs: [kfcc, core] }}),
          }};
        }}
        if (value.includes('/actions/runs/701/jobs?per_page=20')) {{
          return {{
            ok: true, status: 200,
            json: async () => ({{ jobs: [{{ steps: coreSteps }}] }}),
          }};
        }}
        if (value.includes('/actions/runs/702/jobs?per_page=20')) {{
          return {{
            ok: true, status: 200,
            json: async () => ({{ jobs: [{{ steps: kfccSteps }}] }}),
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
    assert result["source_status"] == "healthy"
    assert result["failed_sources"] == []
    assert result["missing_sources"] == []
    assert result["status"] == "normal"
