from pathlib import Path

path = Path("tests/test_collection_sla_api.py")
text = path.read_text(encoding="utf-8")
replacements = {
    "          return {{ ok: true, status: 200, json: async () => ({{ workflow_runs: scheduledRuns }}) }};": (
        "          return {{\n"
        "            ok: true, status: 200,\n"
        "            json: async () => ({{ workflow_runs: scheduledRuns }}),\n"
        "          }};"
    ),
    "          return {{ ok: true, status: 200, json: async () => ({{ jobs: [{{ steps: kfccSteps }}] }}) }};": (
        "          return {{\n"
        "            ok: true, status: 200,\n"
        "            json: async () => ({{ jobs: [{{ steps: kfccSteps }}] }}),\n"
        "          }};"
    ),
    "          return {{ ok: true, status: 200, json: async () => ({{ jobs: [{{ steps: coreSteps }}] }}) }};": (
        "          return {{\n"
        "            ok: true, status: 200,\n"
        "            json: async () => ({{ jobs: [{{ steps: coreSteps }}] }}),\n"
        "          }};"
    ),
}
for old, new in replacements.items():
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one lint target, got {count}: {old}")
    text = text.replace(old, new, 1)
path.write_text(text.rstrip() + "\n", encoding="utf-8")
