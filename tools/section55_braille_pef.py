#!/usr/bin/env python3
"""Local, optional Section 55 JSON BookDocument to UNVERIFIED six-dot PEF.

Example (with a separately installed and licensed python-louis + qualified
table; this command alone NEVER creates print-ready certification):

  python tools/section55_braille_pef.py \
    --book-json book.json --table-file /path/to/ueb-g1.ctb \
    --table-id /path/to/ueb-g1.ctb --table-version local-verified \
    --language en --device-model UNQUALIFIED-SAMPLE \
    --cells-per-line 32 --lines-per-page 25 \
    --rights-confirmed --rights-basis 'owned and authorized' \
    --output-folder ./output-unique
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

# Support direct command invocation from the repository checkout, with no pip install.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acs.bookdocument import BookDocument
from acs.chess_braille_brf import NABCC_DISPLAY_TABLE, pef_to_provisional_brf
from acs.chess_braille_factory import (
    BrailleFactoryError, BrailleProfile, LiblouisTranslator, prepare_chess_book_pef,
)

MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_TABLE_BYTES = 2 * 1024 * 1024


def bounded_read(path: Path, max_size: int) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(max_size + 1)
    if len(raw) > max_size:
        raise BrailleFactoryError("Input resource exceeds local size limit")
    return raw


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Prepare unverified chess-book PEF locally")
    p.add_argument("--book-json", type=Path, required=True)
    p.add_argument("--table-file", type=Path, required=True)
    p.add_argument("--table-id", required=True)
    p.add_argument("--table-version", required=True)
    p.add_argument("--language", required=True)
    p.add_argument("--device-model", required=True)
    p.add_argument("--cells-per-line", type=int, required=True)
    p.add_argument("--lines-per-page", type=int, required=True)
    p.add_argument("--rights-confirmed", action="store_true")
    p.add_argument("--rights-basis", required=True)
    p.add_argument("--output-folder", type=Path, required=True)
    p.add_argument("--emit-brf", action="store_true", help="Also write unverified NABCC BRF (requires explicit selected display map)")
    p.add_argument("--display-table", choices=[NABCC_DISPLAY_TABLE], help="Explicit provisional BRF display mapping")
    return p


def run(args: argparse.Namespace) -> int:
    if not args.rights_confirmed:
        raise BrailleFactoryError("Use --rights-confirmed only for an authorized source")
    # This CLI does not make remote requests or send sources to hosted models.
    try:
        payload = json.loads(bounded_read(args.book_json, MAX_JSON_BYTES).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrailleFactoryError("Invalid UTF-8 canonical BookDocument JSON") from exc
    if type(payload) is not dict:
        raise BrailleFactoryError("Book source must be canonical BookDocument JSON")
    document = BookDocument.from_dict(payload)
    # Never fingerprint one table and invoke a different one through Liblouis.
    try:
        matches = Path(args.table_id).samefile(args.table_file)
    except (OSError, ValueError):
        matches = False
    if not matches:
        raise BrailleFactoryError("The selected Liblouis table ID must identify the exact pinned local table file")
    table_data = bounded_read(args.table_file, MAX_TABLE_BYTES)
    translator = LiblouisTranslator(
        table_id=args.table_id, table_version=args.table_version,
        table_bytes=table_data,
    )
    profile = BrailleProfile(
        language=args.language,
        table_id=translator.table_id,
        table_version=translator.table_version,
        table_sha256=translator.table_sha256,
        device_model=args.device_model,
        cells_per_line=args.cells_per_line,
        lines_per_page=args.lines_per_page,
    )
    result = prepare_chess_book_pef(
        document, profile, translator, rights_confirmed=True,
        rights_basis=args.rights_basis,
    )
    if args.emit_brf and args.display_table != NABCC_DISPLAY_TABLE:
        raise BrailleFactoryError("BRF output requires explicit --display-table en-us-brf.dis")
    if not args.emit_brf and args.display_table is not None:
        raise BrailleFactoryError("BRF display mapping was selected without --emit-brf")
    brf = pef_to_provisional_brf(result, display_table=args.display_table) if args.emit_brf else None
    if bounded_read(args.table_file, MAX_TABLE_BYTES) != table_data:
        raise BrailleFactoryError("Braille table changed during translation; no output published")
    # Refuse clobber or partial publication into a previously accepted folder.
    # A new private temporary folder is assembled on the destination filesystem.
    target = args.output_folder
    if target.exists():
        raise BrailleFactoryError("Output folder exists: refusing overwrite")
    if not target.parent.is_dir():
        raise BrailleFactoryError("Output folder parent does not exist")
    temporary = Path(tempfile.mkdtemp(prefix=".section55-unverified-", dir=str(target.parent)))
    try:
        (temporary / "chess-book-unverified.pef").write_bytes(result.pef)
        if brf is not None:
            (temporary / "chess-book-unverified.brf").write_bytes(brf.data)
        report = {
            "manifest": {**result.manifest, **({
                "output_brf_sha256": brf.sha256, "brf_display_table": brf.display_table,
                "brf_print_ready": False,
            } if brf is not None else {})},
            "warnings": list(result.warnings),
            "notice": "UNVERIFIED; NOT APPROVED FOR DIRECT EMBOSSING OR DISTRIBUTION",
        }
        (temporary / "quality-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    print("SECTION 55: UNVERIFIED_REQUIRES_DECISION")
    print("PEF" + (" and BRF" if brf is not None else "") + " and quality report prepared locally; print readiness NOT established.")
    return 0


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    try:
        return run(args)
    except (BrailleFactoryError, OSError, ValueError) as exc:
        print(f"SECTION 55: NO OUTPUT — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
