from __future__ import annotations

"""Transient compatibility probe for the exact real 2CBV corpus and pinned uncbv.

The chess payload is downloaded into a TemporaryDirectory only.  The report
contains hashes, sizes, return codes and suffix/count topology; source bytes,
entry names and extracted file contents are never persisted as evidence.
"""

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from typing import Iterable

from scripts.v2_2cbv_real_paired_corpus_probe import fetch_bytes, MAX_DOWNLOAD_BYTES

SOURCE_URL = (
    "https://www.sv-mattnetz-berlin.de/wp-content/uploads/2024/04/"
    "Berliner-Meisterschaft-2024.2cbv"
)
SOURCE_SHA256 = "6707e6f2c59978cebf00738505f0e59fc6692ac3e5c88bf05d4528a8197efd8d"
SOURCE_SIZE = 40857
MAX_CAPTURE_BYTES = 1024 * 1024
MAX_EXTRACTED_FILES = 1024
MAX_EXTRACTED_BYTES = 64 * 1024 * 1024


class ProbeError(RuntimeError):
    pass


def _suffix_histogram(names: Iterable[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for raw in names:
        name = raw.strip().replace("\\", "/")
        if not name:
            continue
        suffix = PurePosixPath(name).suffix.casefold() or "<none>"
        counts[suffix] += 1
    return dict(sorted(counts.items()))


def _run(binary: Path, args: list[str], *, cwd: Path) -> dict[str, object]:
    try:
        completed = subprocess.run(
            [os.fspath(binary), *args],
            cwd=os.fspath(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"timed_out": True, "returncode": None}
    stdout = completed.stdout
    stderr = completed.stderr
    if len(stdout) > MAX_CAPTURE_BYTES or len(stderr) > MAX_CAPTURE_BYTES:
        raise ProbeError("uncbv output exceeded the evidence capture bound")
    try:
        lines = stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError:
        lines = []
    return {
        "timed_out": False,
        "returncode": completed.returncode,
        "stdout_bytes": len(stdout),
        "stdout_sha256": sha256(stdout).hexdigest(),
        "stderr_bytes": len(stderr),
        "stderr_sha256": sha256(stderr).hexdigest(),
        "listed_entry_count": len([line for line in lines if line.strip()]),
        "listed_suffixes": _suffix_histogram(lines),
    }


def _scan_extracted(root: Path) -> dict[str, object]:
    count = 0
    total = 0
    suffixes: Counter[str] = Counter()
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for dirname in dirs:
            child = current_path / dirname
            if child.is_symlink():
                raise ProbeError("uncbv produced a symlink directory")
        for filename in files:
            child = current_path / filename
            if child.is_symlink() or not child.is_file():
                raise ProbeError("uncbv produced a non-regular file")
            count += 1
            total += child.stat().st_size
            suffixes[child.suffix.casefold() or "<none>"] += 1
            if count > MAX_EXTRACTED_FILES or total > MAX_EXTRACTED_BYTES:
                raise ProbeError("uncbv extraction exceeded the evidence bound")
    return {
        "file_count": count,
        "total_bytes": total,
        "suffixes": dict(sorted(suffixes.items())),
    }


def run_probe(binary: Path, expected_binary_sha256: str) -> dict[str, object]:
    binary = binary.resolve(strict=True)
    if not binary.is_file():
        raise ProbeError("uncbv binary is not a regular file")
    backend_sha = sha256(binary.read_bytes()).hexdigest()
    if backend_sha != expected_binary_sha256:
        raise ProbeError("uncbv binary identity mismatch")

    payload, final_url, _headers = fetch_bytes(SOURCE_URL, limit=MAX_DOWNLOAD_BYTES)
    source_sha = sha256(payload).hexdigest()
    if len(payload) != SOURCE_SIZE or source_sha != SOURCE_SHA256:
        raise ProbeError("real 2CBV source identity changed")

    report: dict[str, object] = {
        "schema_version": 1,
        "format": "2CBV",
        "source_url": SOURCE_URL,
        "final_url": final_url,
        "source_size": len(payload),
        "source_sha256": source_sha,
        "backend_sha256": backend_sha,
        "payload_persisted": False,
        "payload_uploaded_as_artifact": False,
        "support_promotion_allowed": False,
    }

    with tempfile.TemporaryDirectory(prefix="acs-2cbv-probe-") as td:
        root = Path(td)
        original = root / "source.2cbv"
        alias = root / "source.cbv"
        original.write_bytes(payload)
        shutil.copyfile(original, alias)

        original_list = _run(binary, ["list", os.fspath(original)], cwd=root)
        alias_list = _run(binary, ["list", os.fspath(alias)], cwd=root)
        report["list_original_2cbv"] = original_list
        report["list_cbv_alias"] = alias_list

        alias_list_ok = alias_list.get("returncode") == 0 and not alias_list.get("timed_out")
        original_list_ok = original_list.get("returncode") == 0 and not original_list.get("timed_out")
        report["backend_recognizes_original_extension"] = bool(original_list_ok)
        report["backend_recognizes_payload_when_renamed_cbv"] = bool(alias_list_ok)

        if alias_list_ok:
            output = root / "extracted"
            output.mkdir()
            extraction = _run(
                binary,
                ["extract", os.fspath(alias), f"--output={output}", "--no-confirm"],
                cwd=root,
            )
            report["extract_cbv_alias"] = extraction
            if extraction.get("returncode") == 0 and not extraction.get("timed_out"):
                report["extracted_topology"] = _scan_extracted(output)
                report["backend_can_extract_payload"] = True
            else:
                report["backend_can_extract_payload"] = False
        else:
            report["backend_can_extract_payload"] = False

    topology = report.get("extracted_topology")
    suffixes = topology.get("suffixes", {}) if isinstance(topology, dict) else {}
    report["extracts_modern_2cbh_family"] = bool(
        report["backend_can_extract_payload"]
        and isinstance(suffixes, dict)
        and suffixes.get(".2cbh", 0) == 1
    )
    report["decoder_qualified"] = False
    report["semantic_acceptance_executed"] = False
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uncbv", required=True)
    parser.add_argument("--uncbv-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = run_probe(Path(args.uncbv), args.uncbv_sha256)
    output = Path(args.output)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
