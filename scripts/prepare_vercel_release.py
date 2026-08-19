"""Enable exactly one Vercel Git release for a staged rate-data payload.

The repository-level ``vercel.json`` disables automatic Git deployments. Collection
workflows copy that file unchanged, so their rate-data commits only refresh the live
payload. A publish-only release calls this script on ``stage/vercel.json`` before the
same branch is pushed; Vercel then sees an explicit allow rule for rate-data.
"""

import argparse
import json
from pathlib import Path

RELEASE_BRANCH = "rate-data"


def enable_release(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["git"] = {
        "deploymentEnabled": {
            "*": False,
            RELEASE_BRANCH: True,
        }
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    enable_release(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
