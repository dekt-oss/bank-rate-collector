from pathlib import Path

module = Path("src/rate_monitor/collectors/cu/resumable_funding.py")
test = Path("tests/test_cu_funding_resumable.py")
text = module.read_text(encoding="utf-8")
tests = test.read_text(encoding="utf-8")

text = text.replace(
    "from dataclasses import dataclass\nfrom datetime import UTC, datetime\nfrom pathlib import Path\nfrom typing import Any, Callable\n",
    "from collections.abc import Callable\nfrom dataclasses import dataclass\nfrom datetime import UTC, datetime\nfrom pathlib import Path\nfrom typing import Any\n",
)
text = text.replace(
    'FetchTarget = Callable[..., tuple[list[CuFundingPoint], list[RawArtifactData], dict[int, int], list[str]]]\n',
    'FetchTarget = Callable[\n    ..., tuple[list[CuFundingPoint], list[RawArtifactData], dict[int, int], list[str]]\n]\n',
)
tests = tests.replace(
    "from rate_monitor.collectors.cu.funding import (\n    DisclosureRecord,\n    SOURCE_ID,\n    parse_summary_point,\n)\n",
    "from rate_monitor.collectors.cu.funding import (\n    SOURCE_ID,\n    DisclosureRecord,\n    parse_summary_point,\n)\n",
)
module.write_text(text, encoding="utf-8")
test.write_text(tests, encoding="utf-8")
