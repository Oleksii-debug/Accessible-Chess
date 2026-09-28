from __future__ import annotations

"""Generate deterministic unsigned SLSA Provenance v1 for a qualified release."""

import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acs.slsa_provenance import ProvenanceError, generate_provenance_file


def _reject_builder_identity_mismatch(input_path: str) -> None:
    """Bind builder identity to the exact declared workflow source tuple."""

    try:
        raw = Path(input_path).read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        # Canonical core loading owns detailed file/JSON/duplicate-key errors.
        return
    if type(value) is not dict:
        return
    workflow = value.get("workflow")
    if type(workflow) is not dict:
        return
    repository = workflow.get("repository")
    workflow_path = workflow.get("workflow_path")
    ref = workflow.get("ref")
    builder_id = workflow.get("builder_id")
    if not all(type(item) is str for item in (repository, workflow_path, ref, builder_id)):
        return
    expected = f"{repository}/{workflow_path}@{ref}"
    if builder_id != expected:
        raise ProvenanceError(
            "builder_id must exactly identify the declared repository/workflow_path/ref"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="qualified provenance manifest JSON")
    parser.add_argument("--output", required=True, help="destination in-toto statement JSON")
    args = parser.parse_args(argv)
    try:
        _reject_builder_identity_mismatch(args.input)
        generate_provenance_file(args.input, args.output)
    except ProvenanceError as exc:
        print(f"Provenance generation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
