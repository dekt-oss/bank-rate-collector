# ruff: noqa: E501
"""관리자 collect API가 core/NH 독립 workflow를 실제 JS 경로로 dispatch하는지 검증한다."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECT_API = (ROOT / "web/api/collect.js").as_uri()


def _node(script: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_one_admin_click_dispatches_core_and_nh_with_split_inputs() -> None:
    script = f"""
      import handler from {json.dumps(COLLECT_API)};
      process.env.GITHUB_DISPATCH_TOKEN = 'test-token';
      process.env.GITHUB_REPOSITORY = 'dekt-oss/bank-rate-collector';
      const dispatches = [];
      globalThis.fetch = async (url, init = {{}}) => {{
        const value = String(url);
        if (value.includes('/runs?per_page=30')) {{
          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: [] }}) }};
        }}
        if (value.includes('/dispatches')) {{
          dispatches.push({{ url: value, body: JSON.parse(init.body) }});
          return {{ ok: true, status: 204 }};
        }}
        throw new Error(`unexpected URL: ${{value}}`);
      }};
      let payload = null;
      const res = {{
        setHeader() {{}},
        status(code) {{ this.statusCode = code; return this; }},
        send(body) {{ payload = JSON.parse(body); }},
      }};
      await handler({{
        method: 'POST',
        body: {{ password: 'pw', kfcc_scope: '부산', nh_local_scope: '수도권', skip_fsb: true }},
      }}, res);
      console.log(JSON.stringify({{ status: res.statusCode, payload, dispatches }}));
    """
    result = _node(script)
    assert result["status"] == 202
    assert result["payload"]["ok"] is True
    assert len(result["dispatches"]) == 2

    by_workflow = {
        item["url"].split("/workflows/", 1)[1].split("/dispatches", 1)[0]: item["body"]
        for item in result["dispatches"]
    }
    assert by_workflow["collect.yml"] == {
        "ref": "main",
        "inputs": {
            "password": "pw",
            "kfcc_scope": "부산",
            "skip_fsb": "true",
        },
    }
    assert by_workflow["collect-nh.yml"] == {
        "ref": "main",
        "inputs": {"password": "pw", "nh_local_scope": "수도권"},
    }


def test_partial_dispatch_failure_is_reported() -> None:
    script = f"""
      import handler from {json.dumps(COLLECT_API)};
      process.env.GITHUB_DISPATCH_TOKEN = 'test-token';
      process.env.GITHUB_REPOSITORY = 'dekt-oss/bank-rate-collector';
      globalThis.fetch = async (url) => {{
        const value = String(url);
        if (value.includes('/runs?per_page=30')) {{
          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: [] }}) }};
        }}
        if (value.includes('/workflows/collect.yml/dispatches')) return {{ ok: true, status: 204 }};
        if (value.includes('/workflows/collect-nh.yml/dispatches')) return {{ ok: false, status: 503 }};
        throw new Error(`unexpected URL: ${{value}}`);
      }};
      let payload = null;
      const res = {{
        setHeader() {{}},
        status(code) {{ this.statusCode = code; return this; }},
        send(body) {{ payload = JSON.parse(body); }},
      }};
      await handler({{ method: 'POST', body: {{ password: 'pw' }} }}, res);
      console.log(JSON.stringify({{ status: res.statusCode, payload }}));
    """
    result = _node(script)
    assert result["status"] == 502
    assert result["payload"]["ok"] is False
    assert result["payload"]["partial"] is True


def test_active_independent_nh_blocks_another_admin_collection() -> None:
    script = f"""
      import handler from {json.dumps(COLLECT_API)};
      process.env.GITHUB_DISPATCH_TOKEN = 'test-token';
      process.env.GITHUB_REPOSITORY = 'dekt-oss/bank-rate-collector';
      let dispatchCount = 0;
      globalThis.fetch = async (url) => {{
        const value = String(url);
        if (value.includes('/workflows/collect.yml/runs?per_page=30')) {{
          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: [] }}) }};
        }}
        if (value.includes('/workflows/collect-nh.yml/runs?per_page=30')) {{
          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: [{{
            id: 77, event: 'schedule', status: 'in_progress', conclusion: null,
            run_started_at: new Date().toISOString(), html_url: 'https://example.test/nh-77',
          }}] }}) }};
        }}
        if (value.includes('/dispatches')) {{ dispatchCount += 1; return {{ ok: true, status: 204 }}; }}
        throw new Error(`unexpected URL: ${{value}}`);
      }};
      let payload = null;
      const res = {{
        setHeader() {{}},
        status(code) {{ this.statusCode = code; return this; }},
        send(body) {{ payload = JSON.parse(body); }},
      }};
      await handler({{ method: 'POST', body: {{ password: 'pw' }} }}, res);
      console.log(JSON.stringify({{ status: res.statusCode, payload, dispatchCount }}));
    """
    result = _node(script)
    assert result["status"] == 409
    assert result["payload"]["ok"] is False
    assert result["dispatchCount"] == 0
