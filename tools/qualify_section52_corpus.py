"""Command-line adapter for the canonical Section 52 staging-policy verifier.

Example:
python -m tools.qualify_section52_corpus --stage staged-corpus --manifest rights.json

The output is a narrow policy receipt; packaging and legal gates stay separate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

from acs.section52_distribution_qualification import (
    DistributionQualificationError, qualify_distribution_corpus,
)


def _current_source_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        capture_output=True, check=True, text=True, timeout=10,
        cwd=Path(__file__).resolve().parents[1],
    )
    sha = completed.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise DistributionQualificationError("exact source commit is unavailable")
    return sha


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a staged Section 52 content inventory")
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    try:
        evidence = qualify_distribution_corpus(
            stage_dir=args.stage,
            manifest_path=args.manifest,
            expected_source_sha=_current_source_sha(),
        )
    except (DistributionQualificationError, OSError, subprocess.SubprocessError):
        parser.exit(2, "Section 52 staged content verification failed. No release was published.\n")
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
