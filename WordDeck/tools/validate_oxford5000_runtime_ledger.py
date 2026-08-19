#!/usr/bin/env python3
"""Validate the Oxford 5000 additions that WordDeck actually activates at runtime.

This build-time tool deliberately separates three concepts:
1. verified + activated rows (the exact C# runtime ledger),
2. staged fail-closed rows that are known but not active,
3. the still-unresolved global official Oxford 5000-exclusive inventory.

It reconstructs the activated ledger from ReviewedOxford5000Bootstrap.cs and the
embedded QA resources declared by WordDeck.csproj, then cross-checks stable IDs,
POS/CEFR, translations, duplicates and the C# expected-count invariant.

No network access is performed.
"""
from __future__ import annotations

import argparse
import csv
import re
import tempfile
from collections import Counter
from pathlib import Path

import canonicalize_oxford5000_reviewed as legacy

ALLOWED_LEVELS = {"B2", "C1"}
FAIL_CLOSED_STATUSES = {
    "pending_translation_qa",
    "ambiguous_source",
    "unresolved_sense",
    "blocked_license",
}
SOURCE_SLICE_GLOB = "oxford5000_source_after_*.tsv"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def parse_int_constants(source: str) -> dict[str, int]:
    constants: dict[str, int] = {}
    for name, value in re.findall(
        r"(?:private|public|internal)\s+const\s+int\s+(\w+)\s*=\s*(\d+)\s*;",
        source,
    ):
        constants[name] = int(value)
    return constants


def resolve_int(token: str, constants: dict[str, int]) -> int:
    token = token.strip()
    if token.isdigit():
        return int(token)
    if token not in constants:
        raise ValueError(f"Unknown C# integer token in Oxford runtime ledger: {token!r}")
    return constants[token]


def parse_runtime_slices(source: str) -> list[tuple[str, str, str]]:
    calls = re.findall(
        r'AppendVerifiedSlice\s*\(\s*result\s*,\s*"([^"]+)"\s*,\s*([^,\)]+)\s*,\s*([^)]+)\)',
        source,
    )
    if not calls:
        raise ValueError("No AppendVerifiedSlice calls were found in ReviewedOxford5000Bootstrap.cs")
    names = [name for name, _, _ in calls]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate AppendVerifiedSlice resource names: {names}")
    return calls


def parse_embedded_source_slices(csproj_text: str) -> set[str]:
    includes = re.findall(r'<EmbeddedResource\s+Include="([^"]+)"\s*/>', csproj_text)
    result: set[str] = set()
    for include in includes:
        normalized = include.replace("\\", "/")
        name = Path(normalized).name
        if name.startswith("oxford5000_source_after_") and name.endswith(".tsv"):
            result.add(name)
    return result


def required(row: dict[str, str], field: str, path: Path, row_number: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise ValueError(f"{path.name} row {row_number} has blank required field {field!r}")
    return value


def validate_verified_slice(
    path: Path,
    expected_rows: int,
) -> list[dict[str, str]]:
    rows = read_tsv(path)
    if len(rows) != expected_rows:
        raise ValueError(
            f"{path.name}: expected {expected_rows} runtime rows, found {len(rows)}"
        )

    output: list[dict[str, str]] = []
    for number, row in enumerate(rows, start=1):
        status = required(row, "status", path, number)
        if status != "verified":
            raise ValueError(
                f"{path.name} row {number}: runtime activation refuses status {status!r}"
            )
        source = required(row, "source", path, number)
        pos = required(row, "part_of_speech", path, number)
        level = required(row, "level", path, number).upper()
        target = required(row, "ukrainian", path, number)
        entry_id = required(row, "entry_id", path, number)
        if level not in ALLOWED_LEVELS:
            raise ValueError(f"{path.name} row {number}: invalid Oxford 5000 level {level!r}")
        expected_id = legacy.lexical_entry_id(source, pos, level)
        if entry_id != expected_id:
            raise ValueError(
                f"{path.name} row {number}: stable ID mismatch for "
                f"{source!r}/{pos}/{level}: {entry_id!r} != {expected_id!r}"
            )
        output.append(
            {
                "entry_id": entry_id,
                "source": source,
                "part_of_speech": pos,
                "level": level,
                "ukrainian": target,
                "status": status,
                "origin": path.name,
            }
        )
    return output


def validate_staged_slice(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for number, row in enumerate(read_tsv(path), start=1):
        source = required(row, "source", path, number)
        pos = required(row, "part_of_speech", path, number)
        level = required(row, "level", path, number).upper()
        entry_id = required(row, "entry_id", path, number)
        status = required(row, "status", path, number)
        if level not in ALLOWED_LEVELS:
            raise ValueError(f"{path.name} row {number}: invalid staged level {level!r}")
        expected_id = legacy.lexical_entry_id(source, pos, level)
        if entry_id != expected_id:
            raise ValueError(
                f"{path.name} row {number}: staged stable ID mismatch "
                f"{entry_id!r} != {expected_id!r}"
            )
        if status == "verified":
            if not (row.get("ukrainian") or "").strip():
                raise ValueError(
                    f"{path.name} row {number}: verified staged row has blank Ukrainian translation"
                )
            counts["verified_not_activated"] += 1
        elif status in FAIL_CLOSED_STATUSES:
            if status == "pending_translation_qa" and (row.get("ukrainian") or "").strip():
                raise ValueError(
                    f"{path.name} row {number}: pending_translation_qa row already has a "
                    "translation; verify it or clear it instead of leaving ambiguous state"
                )
            counts[status] += 1
        else:
            raise ValueError(
                f"{path.name} row {number}: unsupported fail-closed status {status!r}"
            )
    return counts


def ensure_unique(rows: list[dict[str, str]]) -> None:
    ids: set[str] = set()
    identities: set[tuple[str, str, str]] = set()
    for row in rows:
        entry_id = row["entry_id"]
        identity = (
            row["source"].casefold(),
            row["part_of_speech"].casefold(),
            row["level"].upper(),
        )
        if entry_id in ids:
            raise ValueError(f"Duplicate runtime Oxford stable ID: {entry_id}")
        if identity in identities:
            raise ValueError(f"Duplicate runtime Oxford lexical identity: {identity}")
        ids.add(entry_id)
        identities.add(identity)


def build_runtime_ledger(worddeck_dir: Path) -> tuple[list[dict[str, str]], Counter[str], list[str]]:
    qa_dir = worddeck_dir / "QA"
    bootstrap_path = worddeck_dir / "ReviewedOxford5000Bootstrap.cs"
    csproj_path = worddeck_dir / "WordDeck.csproj"

    bootstrap_text = bootstrap_path.read_text(encoding="utf-8")
    csproj_text = csproj_path.read_text(encoding="utf-8")
    constants = parse_int_constants(bootstrap_text)
    if "ExpectedCanonicalRows" not in constants:
        raise ValueError("ReviewedOxford5000Bootstrap.cs does not expose ExpectedCanonicalRows")

    legacy_rows = legacy.canonicalize(qa_dir)
    runtime_rows = [
        {
            "entry_id": row.entry_id,
            "source": row.source,
            "part_of_speech": row.part_of_speech,
            "level": row.level,
            "ukrainian": row.ukrainian,
            "status": row.status,
            "origin": "legacy-reviewed-0001-0200",
        }
        for row in legacy_rows
    ]

    calls = parse_runtime_slices(bootstrap_text)
    runtime_slice_names = [name for name, _, _ in calls]
    embedded_slice_names = parse_embedded_source_slices(csproj_text)

    missing_embeds = sorted(set(runtime_slice_names) - embedded_slice_names)
    extra_embeds = sorted(embedded_slice_names - set(runtime_slice_names))
    if missing_embeds:
        raise ValueError(
            "Runtime bootstrap references Oxford slices not embedded by WordDeck.csproj: "
            + ", ".join(missing_embeds)
        )
    if extra_embeds:
        raise ValueError(
            "WordDeck.csproj embeds Oxford source slices not activated by runtime bootstrap: "
            + ", ".join(extra_embeds)
        )

    for file_name, expected_token, _major_order in calls:
        expected_rows = resolve_int(expected_token, constants)
        runtime_rows.extend(validate_verified_slice(qa_dir / file_name, expected_rows))

    ensure_unique(runtime_rows)
    expected_runtime = constants["ExpectedCanonicalRows"]
    if len(runtime_rows) != expected_runtime:
        raise ValueError(
            f"Runtime Oxford ledger count mismatch: C# expects {expected_runtime}, "
            f"reconstructed {len(runtime_rows)}"
        )

    staged_counts: Counter[str] = Counter()
    staged_files: list[str] = []
    for path in sorted(qa_dir.glob(SOURCE_SLICE_GLOB), key=lambda p: p.name.casefold()):
        if path.name in runtime_slice_names:
            continue
        counts = validate_staged_slice(path)
        staged_counts.update(counts)
        staged_files.append(path.name)

    activated_ids = {row["entry_id"] for row in runtime_rows}
    activated_identities = {
        (row["source"].casefold(), row["part_of_speech"].casefold(), row["level"].upper())
        for row in runtime_rows
    }
    staged_ids: set[str] = set()
    staged_identities: set[tuple[str, str, str]] = set()
    for file_name in staged_files:
        path = qa_dir / file_name
        for number, row in enumerate(read_tsv(path), start=1):
            entry_id = required(row, "entry_id", path, number)
            identity = (
                required(row, "source", path, number).casefold(),
                required(row, "part_of_speech", path, number).casefold(),
                required(row, "level", path, number).upper(),
            )
            if entry_id in activated_ids or identity in activated_identities:
                raise ValueError(
                    f"{file_name} row {number}: staged row collides with activated runtime row"
                )
            if entry_id in staged_ids or identity in staged_identities:
                raise ValueError(
                    f"{file_name} row {number}: staged row duplicates another staged row"
                )
            staged_ids.add(entry_id)
            staged_identities.add(identity)

    return runtime_rows, staged_counts, staged_files


def write_ledger(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "entry_id",
        "source",
        "part_of_speech",
        "level",
        "ukrainian",
        "status",
        "origin",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    rows: list[dict[str, str]],
    staged_counts: Counter[str],
    staged_files: list[str],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged_total = sum(staged_counts.values())
    lines = [
        ("metric", "value"),
        ("verified_activated", str(len(rows))),
        ("staged_total", str(staged_total)),
        ("staged_files", str(len(staged_files))),
        ("pending_translation_qa", str(staged_counts["pending_translation_qa"])),
        ("ambiguous_source", str(staged_counts["ambiguous_source"])),
        ("unresolved_sense", str(staged_counts["unresolved_sense"])),
        ("blocked_license", str(staged_counts["blocked_license"])),
        ("verified_not_activated", str(staged_counts["verified_not_activated"])),
        ("known_accounted_local", str(len(rows) + staged_total)),
        ("global_official_inventory_complete", "NO"),
        ("global_remaining_unaccounted", "UNKNOWN"),
        ("stage1_ready_for_pass", "NO"),
        (
            "stage1_reason",
            "Full official Oxford 5000-exclusive inventory has not yet been committed and reconciled.",
        ),
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerows(lines)


def self_test() -> None:
    code = """
private const int StandardSliceRows = 29;
public const int ExpectedCanonicalRows = 896;
AppendVerifiedSlice(result, "a.tsv", StandardSliceRows, 2018);
AppendVerifiedSlice(result, "b.tsv", 43, 2019);
"""
    constants = parse_int_constants(code)
    assert constants == {"StandardSliceRows": 29, "ExpectedCanonicalRows": 896}
    calls = parse_runtime_slices(code)
    assert calls == [
        ("a.tsv", "StandardSliceRows", "2018"),
        ("b.tsv", "43", "2019"),
    ]
    assert resolve_int("StandardSliceRows", constants) == 29
    assert resolve_int("43", constants) == 43

    csproj = r"""
<Project><ItemGroup>
<EmbeddedResource Include="QA\oxford5000_source_after_a.tsv" />
<EmbeddedResource Include="QA\other.tsv" />
</ItemGroup></Project>
"""
    assert parse_embedded_source_slices(csproj) == {"oxford5000_source_after_a.tsv"}

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "slice.tsv"
        source = "sample"
        pos = "noun"
        level = "C1"
        path.write_text(
            "entry_id\tsource\tpart_of_speech\tlevel\tstatus\tukrainian\n"
            f"{legacy.lexical_entry_id(source, pos, level)}\t{source}\t{pos}\t{level}\tverified\tприклад\n",
            encoding="utf-8",
        )
        rows = validate_verified_slice(path, 1)
        assert rows[0]["entry_id"] == legacy.lexical_entry_id(source, pos, level)

    print(
        "Oxford runtime-ledger validator self-test passed: C# constants/calls, "
        "embedded resources and stable-ID verification are deterministic."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--worddeck-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    rows, staged_counts, staged_files = build_runtime_ledger(args.worddeck_dir)
    if args.ledger is not None:
        write_ledger(rows, args.ledger)
    if args.report is not None:
        write_report(rows, staged_counts, staged_files, args.report)

    print(
        "Oxford runtime ledger validated: "
        f"verified_activated={len(rows)}, "
        f"staged={sum(staged_counts.values())}, "
        f"pending_translation_qa={staged_counts['pending_translation_qa']}, "
        "global_remaining_unaccounted=UNKNOWN, Stage 1 ready=NO."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
