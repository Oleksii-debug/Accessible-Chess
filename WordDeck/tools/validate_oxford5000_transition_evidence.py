#!/usr/bin/env python3
"""Bind an Oxford 5000 integration transition verdict to the exact evidence bytes.

Build/development-time only. This wrapper performs no harvesting, translation, or
linguistic judgement. It runs the canonical integration-transition validator and then
records deterministic SHA-256 and byte-size evidence for all six files that prove one
Data Factory -> Content QA -> Work activation transition.

The resulting report can therefore be audited against the exact pre/post runtime and
unaccounted ledgers plus the exact automation handoff that authorized the delta.
No network access is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import tempfile
from pathlib import Path

import validate_oxford5000_integration_transition as transition

CONTRACT = "worddeck-oxford5000-transition-evidence-v1"
INPUTS = (
    ("pre_unaccounted", "--pre-unaccounted"),
    ("data_factory", "--data-factory"),
    ("content_qa", "--content-qa"),
    ("pre_runtime", "--pre-runtime"),
    ("post_runtime", "--post-runtime"),
    ("post_unaccounted", "--post-unaccounted"),
)


def fingerprint(path: Path) -> tuple[str, str]:
    payload = path.read_bytes()
    return hashlib.sha256(payload).hexdigest(), str(len(payload))


def execute(args: argparse.Namespace) -> dict[str, str]:
    transition_args = argparse.Namespace(**vars(args))
    transition_args.report = None
    report = transition.execute(transition_args)
    report["transition_evidence_contract"] = CONTRACT
    for attribute, _flag in INPUTS:
        path = getattr(args, attribute)
        digest, size = fingerprint(path)
        report[f"{attribute}_sha256"] = digest
        report[f"{attribute}_bytes"] = size
    if args.report is not None:
        transition.write_report(report, args.report)
    return report


def run_self_test() -> None:
    transition.run_self_test()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = root / "first.tsv"
        second = root / "second.tsv"
        changed = root / "changed.tsv"
        first.write_bytes(b"a\tb\n1\t2\n")
        second.write_bytes(b"a\tb\n1\t2\n")
        changed.write_bytes(b"a\tb\n1\t3\n")
        first_digest, first_size = fingerprint(first)
        second_digest, second_size = fingerprint(second)
        changed_digest, changed_size = fingerprint(changed)
        if first_digest != second_digest or first_size != second_size:
            raise AssertionError("Identical transition evidence bytes produced different fingerprints")
        if first_digest == changed_digest:
            raise AssertionError("Changed transition evidence bytes did not change SHA-256")
        if first_size != changed_size:
            raise AssertionError("Self-test expects equal-size payloads for content-only digest proof")
    print(
        "Oxford 5000 transition-evidence self-test passed: canonical transition validation "
        "and exact six-file byte fingerprints are deterministic."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-unaccounted", dest="pre_unaccounted", type=Path)
    parser.add_argument("--data-factory", dest="data_factory", type=Path)
    parser.add_argument("--content-qa", dest="content_qa", type=Path)
    parser.add_argument("--pre-runtime", dest="pre_runtime", type=Path)
    parser.add_argument("--post-runtime", dest="post_runtime", type=Path)
    parser.add_argument("--post-unaccounted", dest="post_unaccounted", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    missing = [flag for attribute, flag in INPUTS if getattr(args, attribute) is None]
    if missing:
        parser.error("required for transition evidence: " + ", ".join(missing))
    report = execute(args)
    print(
        "Oxford 5000 transition evidence validated: "
        f"qa_pass_activated={report['qa_pass_activated']}, "
        f"runtime_delta={report['runtime_delta']}, "
        f"unaccounted_delta={report['unaccounted_delta']}, "
        f"contract={report['transition_evidence_contract']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
