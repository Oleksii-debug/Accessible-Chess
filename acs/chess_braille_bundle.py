from __future__ import annotations

"""Offline independent consistency check for a Section-55 provisional package.

This verifier intentionally does not certify literary/chess Braille,
embossers, source rights, translation quality, or real-device accessibility.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from .chess_braille_brf import NABCC_DISPLAY_TABLE, pef_to_provisional_brf
from .chess_braille_factory import BrailleFactoryError, BraillePreparation

PEF_FILE = "chess-book-unverified.pef"
BRF_FILE = "chess-book-unverified.brf"
REPORT_FILE = "quality-report.json"
MAX_PEF_SIZE = 32 * 1024 * 1024
MAX_BRF_SIZE = 32 * 1024 * 1024
MAX_REPORT_SIZE = 64 * 1024
MAX_SOURCE_SIZE = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ProvisionalBundleCheck:
    output_pef_sha256: str
    output_brf_sha256: str | None
    source_sha256: str
    pages: int
    internal_consistency: bool = True
    qualified_print_ready: bool = False
    status: str = "UNVERIFIED_REQUIRES_DECISION"


def _read_regular_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise BrailleFactoryError("A required package file is missing, linked, or not regular")
    with path.open("rb") as f:
        result = f.read(maximum + 1)
    if len(result) > maximum:
        raise BrailleFactoryError("A package file exceeds the bounded verification limit")
    return result


def _expect_hash(data: bytes, expected: object, field: str) -> str:
    digest = sha256(data).hexdigest()
    if type(expected) is not str or digest != expected:
        raise BrailleFactoryError(f"Package hash mismatch: {field}")
    return digest


def verify_provisional_bundle(folder: Path, source_file: Path) -> ProvisionalBundleCheck:
    """Verify exact local source, PEF, optional BRF, and linked report hashes.

    A pass establishes only byte and provisional structure consistency. The
    source must be independently lawfully authorized and qualified externally.
    """
    if type(folder) is not Path or type(source_file) is not Path:
        raise BrailleFactoryError("Local folder and source Path objects are required")
    if folder.is_symlink() or not folder.is_dir():
        raise BrailleFactoryError("Package directory does not exist or is a link")
    entries = {entry.name for entry in folder.iterdir()}
    if entries not in (
        {PEF_FILE, REPORT_FILE},
        {PEF_FILE, BRF_FILE, REPORT_FILE},
    ):
        raise BrailleFactoryError("The provisional package contains missing or unexpected entries")
    raw_report = _read_regular_file(folder / REPORT_FILE, MAX_REPORT_SIZE)
    try:
        report = json.loads(raw_report.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrailleFactoryError("Package report is not canonical readable JSON") from exc
    if type(report) is not dict or type(report.get("manifest")) is not dict:
        raise BrailleFactoryError("Package report lacks a canonical manifest")
    if type(report.get("warnings")) is not list or not report["warnings"]:
        raise BrailleFactoryError("Package report lacks mandatory unverified warnings")
    if report.get("notice") != "UNVERIFIED; NOT APPROVED FOR DIRECT EMBOSSING OR DISTRIBUTION":
        raise BrailleFactoryError("Package notice was removed or changed")
    manifest = report["manifest"]
    if manifest.get("status") != "UNVERIFIED_REQUIRES_DECISION" or manifest.get("print_ready") is not False:
        raise BrailleFactoryError("A provisional report cannot declare print readiness")
    if manifest.get("device_verified") is not False or manifest.get("qualification") != "internal-structural-only":
        raise BrailleFactoryError("Package falsely claims a verified device or qualification")
    if manifest.get("rights_confirmed") is not True:
        raise BrailleFactoryError("Package lacks explicit source-rights declaration")
    if manifest.get("format") != "PEF" or manifest.get("section") != 55:
        raise BrailleFactoryError("Package declares an unexpected format/section")
    source = _read_regular_file(source_file, MAX_SOURCE_SIZE)
    source_sha = _expect_hash(source, manifest.get("original_source_sha256"), "original_source_sha256")
    if type(manifest.get("original_source_size_bytes")) is not int or manifest["original_source_size_bytes"] != len(source):
        raise BrailleFactoryError("Original source byte count mismatches the manifest")
    pef = _read_regular_file(folder / PEF_FILE, MAX_PEF_SIZE)
    pef_sha = _expect_hash(pef, manifest.get("output_pef_sha256"), "output_pef_sha256")
    preparation = BraillePreparation(pef=pef, manifest=manifest, warnings=tuple(report["warnings"]))
    # The normal BRF converter's fail-closed page/layout/metadata gates are
    # reused as an independent PEF structure check even for PEF-only packages.
    reproduced_brf = pef_to_provisional_brf(preparation, display_table=NABCC_DISPLAY_TABLE)
    output_brf: str | None = None
    if BRF_FILE in entries:
        if manifest.get("brf_print_ready") is not False or manifest.get("brf_display_table") != NABCC_DISPLAY_TABLE:
            raise BrailleFactoryError("BRF certification or display table is invalid")
        brf = _read_regular_file(folder / BRF_FILE, MAX_BRF_SIZE)
        output_brf = _expect_hash(brf, manifest.get("output_brf_sha256"), "output_brf_sha256")
        if brf != reproduced_brf.data or reproduced_brf.sha256 != output_brf:
            raise BrailleFactoryError("BRF bytes are not a lossless rendering of the PEF")
    elif any(key in manifest for key in ("output_brf_sha256", "brf_print_ready", "brf_display_table")):
        raise BrailleFactoryError("BRF output claimed but BRF bytes absent")
    return ProvisionalBundleCheck(
        output_pef_sha256=pef_sha,
        output_brf_sha256=output_brf,
        source_sha256=source_sha,
        pages=reproduced_brf.pages,
    )
