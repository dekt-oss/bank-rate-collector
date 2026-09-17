# ruff: noqa: E501
"""Canonical NH attempt를 재사용하는 one-shot 실행도 실시간 수집으로 보인다."""

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


def _script(repository_runs: str, nh_runs: str = "[]", repository_ok: bool = True) -> str:
    return f"""
      import handler from {json.dumps(HEALTH_API)};
      process.env.GITHUB_DISPATCH_TOKEN = 'test-token';
      process.env.GITHUB_REPOSITORY = 'dekt-oss/bank-rate-collector';
      process.env.RATE_MONITOR_HEALTH_NOW = '2026-08-12T06:30:00Z';
      const repositoryRuns = {repository_runs};
      const nhRuns = {nh_runs};
      const nhStep = {{
        name: 'Collect NH local', status: 'in_progress', conclusion: null,
        started_at: '2026-08-12T06:24:45Z', completed_at: null,
      }};
      globalThis.fetch = async (url) => {{
        const value = String(url);
        if (value.includes('/actions/workflows/collect-morning-cycle.yml/runs') ||
            value.includes('/actions/workflows/collect.yml/runs') ||
            value.includes('/actions/workflows/collect-institution-funding.yml/runs')) {{
          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: [] }}) }};
        }}
        if (value.includes('/actions/workflows/collect-nh.yml/runs?per_page=30')) {{
          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: nhRuns }}) }};
        }}
        if (value.endsWith('/actions/runs?per_page=50')) {{
          return {str(repository_ok).lower()}
            ? {{ ok: true, status: 200, json: async () => ({{ workflow_runs: repositoryRuns }}) }}
            : {{ ok: false, status: 503, json: async () => ({{}}) }};
        }}
        if (value.includes('/actions/runs/701/jobs?per_page=20') ||
            value.includes('/actions/runs/721/jobs?per_page=20')) {{
          return {{ ok: true, status: 200, json: async () => ({{ jobs: [{{ steps: [nhStep] }}] }}) }};
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
      console.log(JSON.stringify(payload));
    """


def test_active_one_shot_using_nh_attempt_is_reported_as_current_collection() -> None:
    repository_runs = """[{
      id: 702, run_number: 99, name: 'CI', path: '.github/workflows/ci.yml', event: 'push',
      status: 'in_progress', conclusion: null, created_at: '2026-08-12T06:23:00Z',
      run_started_at: '2026-08-12T06:23:00Z', updated_at: '2026-08-12T06:23:30Z',
      html_url: 'https://example.test/ci', referenced_workflows: []
    }, {
      id: 701, run_number: 1, name: 'NH post-merge one-shot test',
      path: '.github/workflows/nh-postmerge-test.yml', event: 'push', status: 'in_progress',
      conclusion: null, created_at: '2026-08-12T06:22:40Z', run_started_at: '2026-08-12T06:22:40Z',
      updated_at: '2026-08-12T06:24:17Z', html_url: 'https://example.test/nh-one-shot',
      referenced_workflows: [{path: 'dekt-oss/bank-rate-collector/.github/workflows/nh-attempt.yml@abc123'}]
    }]"""
    result = _node(_script(repository_runs))
    assert result["ok"] is True
    assert result["active_collection"]["run_number"] == 1
    assert result["active_collection"]["status"] == "in_progress"
    assert result["source_steps"]["nh_local"]["status"] == "in_progress"


def test_unrelated_active_workflow_is_not_reported_as_collection() -> None:
    repository_runs = """[{
      id: 711, run_number: 100, name: 'CI', path: '.github/workflows/ci.yml', event: 'push',
      status: 'in_progress', conclusion: null, created_at: '2026-08-12T06:23:00Z',
      run_started_at: '2026-08-12T06:23:00Z', updated_at: '2026-08-12T06:23:30Z',
      html_url: 'https://example.test/ci', referenced_workflows: []
    }]"""
    result = _node(_script(repository_runs))
    assert result["ok"] is True
    assert result["active_collection"] is None
    assert result["latest_collection"] is None


def test_indirect_discovery_failure_does_not_hide_canonical_nh_run() -> None:
    nh_runs = """[{
      id: 721, run_number: 42, name: 'Collect NH rates', path: '.github/workflows/collect-nh.yml',
      event: 'workflow_dispatch', status: 'in_progress', conclusion: null,
      created_at: '2026-08-12T06:22:40Z', run_started_at: '2026-08-12T06:22:40Z',
      updated_at: '2026-08-12T06:24:17Z', html_url: 'https://example.test/nh-canonical'
    }]"""
    result = _node(_script("[]", nh_runs=nh_runs, repository_ok=False))
    assert result["ok"] is True
    assert result["active_collection"]["run_number"] == 42
    assert result["active_collection"]["status"] == "in_progress"
    assert result["source_steps"]["nh_local"]["status"] == "in_progress"
