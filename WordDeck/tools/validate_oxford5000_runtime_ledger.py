#!/usr/bin/env python3
"""Validate and reconcile the Oxford 5000 additions WordDeck knows about.

Build-time only. The validator separates:
1. verified + activated rows (the exact C# runtime ledger),
2. staged fail-closed rows that are known but not active,
3. the global official Oxford 5000-exclusive inventory when a saved official HTML
   snapshot is supplied.

Without --official-html the tool still proves the exact local runtime/staging ledger
and reports global remaining coverage as UNKNOWN. With --official-html it uses the
row-preserving official extractor and fails closed on any local source/POS/CEFR row
that is not present in the official exclusive inventory. It then emits an exact
unaccounted tail instead of estimating completion.

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
import extract_oxford5000_official as official

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


def identity_of(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row["source"].strip().casefold(),
        row["part_of_speech"].strip().casefold(),
        row["level"].strip().upper(),
    )


def validate_verified_slice(path: Path, expected_rows: int) -> list[dict[str, str]]:
    rows = read_tsv(path)
    if len(rows) != expected_rows:
        raise ValueError(f"{path.name}: expected {expected_rows} runtime rows, found {len(rows)}")

    output: list[dict[str, str]] = []
    for number, row in enumerate(rows, start=1):
        status = required(row, "status", path, number)
        if status != "verified":
            raise ValueError(f"{path.name} row {number}: runtime activation refuses status {status!r}")
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


def validate_staged_slice(path: Path) -> tuple[Counter[str], list[dict[str, str]]]:
    counts: Counter[str] = Counter()
    output: list[dict[str, str]] = []
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
        ukrainian = (row.get("ukrainian") or "").strip()
        if status == "verified":
            if not ukrainian:
                raise ValueError(f"{path.name} row {number}: verified staged row has blank Ukrainian translation")
            counts["verified_not_activated"] += 1
        elif status in FAIL_CLOSED_STATUSES:
            if status == "pending_translation_qa" and ukrainian:
                raise ValueError(
                    f"{path.name} row {number}: pending_translation_qa row already has a "
                    "translation; verify it or clear it instead of leaving ambiguous state"
                )
            counts[status] += 1
        else:
            raise ValueError(f"{path.name} row {number}: unsupported fail-closed status {status!r}")
        output.append(
            {
                "entry_id": entry_id,
                "source": source,
                "part_of_speech": pos,
                "level": level,
                "ukrainian": ukrainian,
                "status": status,
                "origin": path.name,
            }
        )
    return counts, output


def ensure_unique(rows: list[dict[str, str]], label: str) -> None:
    ids: set[str] = set()
    identities: set[tuple[str, str, str]] = set()
    for row in rows:
        entry_id = row["entry_id"]
        identity = identity_of(row)
        if entry_id in ids:
            raise ValueError(f"Duplicate {label} Oxford stable ID: {entry_id}")
        if identity in identities:
            raise ValueError(f"Duplicate {label} Oxford lexical identity: {identity}")
        ids.add(entry_id)
        identities.add(identity)


def build_runtime_ledger(
    worddeck_dir: Path,
) -> tuple[list[dict[str, str]], Counter[str], list[dict[str, str]], list[str]]:
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

    ensure_unique(runtime_rows, "runtime")
    expected_runtime = constants["ExpectedCanonicalRows"]
    if len(runtime_rows) != expected_runtime:
        raise ValueError(
            f"Runtime Oxford ledger count mismatch: C# expects {expected_runtime}, reconstructed {len(runtime_rows)}"
        )

    staged_counts: Counter[str] = Counter()
    staged_rows: list[dict[str, str]] = []
    staged_files: list[str] = []
    for path in sorted(qa_dir.glob(SOURCE_SLICE_GLOB), key=lambda p: p.name.casefold()):
        if path.name in runtime_slice_names:
            continue
        counts, rows = validate_staged_slice(path)
        staged_counts.update(counts)
        staged_rows.extend(rows)
        staged_files.append(path.name)

    ensure_unique(staged_rows, "staged")
    activated_ids = {row["entry_id"] for row in runtime_rows}
    activated_identities = {identity_of(row) for row in runtime_rows}
    for row in staged_rows:
        if row["entry_id"] in activated_ids or identity_of(row) in activated_identities:
            raise ValueError(f"{row['origin']}: staged row collides with activated runtime row {identity_of(row)}")

    return runtime_rows, staged_counts, staged_rows, staged_files


def reconcile_official(
    runtime_rows: list[dict[str, str]],
    staged_rows: list[dict[str, str]],
    official_html: Path,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    official_rows = official.extract(official_html.read_text(encoding="utf-8"))
    official_by_identity = {
        (row["source"].casefold(), row["part_of_speech"].casefold(), row["level"].upper()): row
        for row in official_rows
    }
    if len(official_by_identity) != len(official_rows):
        raise ValueError("Official extractor returned duplicate lexical identities")

    local_rows = runtime_rows + staged_rows
    local_by_identity = {identity_of(row): row for row in local_rows}
    if len(local_by_identity) != len(local_rows):
        raise ValueError("Local runtime + staged ledger contains duplicate lexical identities")

    local_not_official = sorted(set(local_by_identity) - set(official_by_identity))
    if local_not_official:
        details: list[str] = []
        official_levels_by_word_pos: dict[tuple[str, str], set[str]] = {}
        for identity in official_by_identity:
            official_levels_by_word_pos.setdefault(identity[:2], set()).add(identity[2])
        for source, pos, level in local_not_official[:25]:
            official_levels = sorted(official_levels_by_word_pos.get((source, pos), set()))
            if official_levels:
                details.append(f"{source}/{pos}: local {level}, official {','.join(official_levels)}")
            else:
                details.append(f"{source}/{pos}/{level}: not in official exclusive inventory")
        suffix = "" if len(local_not_official) <= 25 else f"; plus {len(local_not_official) - 25} more"
        raise ValueError("Local Oxford rows disagree with official exclusive inventory: " + "; ".join(details) + suffix)

    unaccounted_identities = [
        identity for identity in official_by_identity if identity not in local_by_identity
    ]
    unaccounted = [official_by_identity[identity] for identity in unaccounted_identities]
    stats = {
        "official_exclusive_rows": len(official_rows),
        "official_accounted_local": len(official_rows) - len(unaccounted),
        "global_remaining_unaccounted": len(unaccounted),
    }
    return unaccounted, stats


def write_ledger(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["entry_id", "source", "part_of_speech", "level", "ukrainian", "status", "origin"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_unaccounted(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "entry_id",
        "source_index",
        "source",
        "part_of_speech",
        "level",
        "definition_path",
        "source_url",
        "status",
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
    official_stats: dict[str, int] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged_total = sum(staged_counts.values())
    inventory_complete = official_stats is not None
    remaining = (
        str(official_stats["global_remaining_unaccounted"])
        if official_stats is not None
        else "UNKNOWN"
    )
    ready = inventory_complete and official_stats["global_remaining_unaccounted"] == 0
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
        ("global_official_inventory_loaded", "YES" if inventory_complete else "NO"),
        (
            "official_exclusive_lexical_rows",
            str(official_stats["official_exclusive_rows"]) if official_stats is not None else "UNKNOWN",
        ),
        (
            "official_accounted_local",
            str(official_stats["official_accounted_local"]) if official_stats is not None else "UNKNOWN",
        ),
        ("global_remaining_unaccounted", remaining),
        ("stage1_inventory_ready_for_audit", "YES" if ready else "NO"),
        (
            "stage1_reason",
            "Every official exclusive lexical row is locally accounted for; formal PASS still belongs to the auditor."
            if ready
            else (
                "Official snapshot loaded but an unaccounted tail remains."
                if inventory_complete
                else "Full saved official Oxford HTML has not yet been supplied to the reconciliation pass."
            ),
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
    assert calls == [("a.tsv", "StandardSliceRows", "2018"), ("b.tsv", "43", "2019")]
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
        temp_dir = Path(temp)
        path = temp_dir / "slice.tsv"
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

        official_html = temp_dir / "official.html"
        official_html.write_text(
            """
<div id="wordlistsContentPanel"><ul>
<li data-hw="sample" data-ox3000="" data-ox5000="c1"><a href="/definition/english/sample">sample</a><span class="pos">noun</span></li>
<li data-hw="tail" data-ox3000="" data-ox5000="b2"><a href="/definition/english/tail">tail</a><span class="pos">noun</span></li>
</ul></div>
""",
            encoding="utf-8",
        )
        unaccounted, stats = reconcile_official(rows, [], official_html)
        assert [row["source"] for row in unaccounted] == ["tail"]
        assert stats == {
            "official_exclusive_rows": 2,
            "official_accounted_local": 1,
            "global_remaining_unaccounted": 1,
        }

        bad = [dict(rows[0], level="B2", entry_id=legacy.lexical_entry_id("sample", "noun", "B2"))]
        try:
            reconcile_official(bad, [], official_html)
        except ValueError as exc:
            assert "local b2, official c1" in str(exc).casefold()
        else:
            raise RuntimeError("Official reconciliation accepted a wrong local CEFR level")

    print(
        "Oxford runtime-ledger validator self-test passed: runtime structure, stable IDs "
        "and optional full official-inventory reconciliation are deterministic."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worddeck-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--official-html", type=Path)
    parser.add_argument("--unaccounted", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    runtime_rows, staged_counts, staged_rows, staged_files = build_runtime_ledger(args.worddeck_dir)
    official_stats: dict[str, int] | None = None
    unaccounted: list[dict[str, str]] = []
    if args.official_html is not None:
        unaccounted, official_stats = reconcile_official(runtime_rows, staged_rows, args.official_html)
    elif args.unaccounted is not None:
        parser.error("--unaccounted requires --official-html")

    if args.ledger is not None:
        write_ledger(runtime_rows, args.ledger)
    if args.report is not None:
        write_report(runtime_rows, staged_counts, staged_files, args.report, official_stats)
    if args.unaccounted is not None:
        write_unaccounted(unaccounted, args.unaccounted)

    remaining = (
        str(official_stats["global_remaining_unaccounted"])
        if official_stats is not None
        else "UNKNOWN"
    )
    print(
        "Oxford ledger validated: "
        f"verified_activated={len(runtime_rows)}, "
        f"staged={sum(staged_counts.values())}, "
        f"pending_translation_qa={staged_counts['pending_translation_qa']}, "
        f"global_remaining_unaccounted={remaining}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
