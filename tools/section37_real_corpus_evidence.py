from __future__ import annotations

"""Materialize bounded Section 37 readback evidence from real external files.

The command is deliberately build/test-time only.  It never downloads into the
runtime, never copies third-party bytes into the repository, and never treats a
filename as proof of ChessBase decoding.  PGN archives are parsed through the
canonical bounded parser; CBV files are first fingerprinted and probed, then
optionally exercised through the pinned external ``uncbv`` + ``libcbh`` bridge.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acs.acsdb import AcsDatabase  # noqa: E402
from acs.cbv_extractor import ExternalCbvExtractorConfig  # noqa: E402
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig  # noqa: E402
from acs.chessbase_library_import import ChessBaseLibraryImportService  # noqa: E402
from acs.chessbase_manifest import build_chessbase_manifest  # noqa: E402
from acs.chessbase_adapter import probe_chessbase_source  # noqa: E402
from acs.pgn_roundtrip import parse_pgn_text  # noqa: E402


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
UNCBV_COMMIT = "3c18e8a7c6a30c21f945a1ab5462521c306dca57"

SOURCES = {
    "cotswold_cbv": {
        "relative": "chessit/cotswold_2023.cbv",
        "url": "https://www.chessit.co.uk/Congresses/Cotswold/2023/Cotswold_Open_2023.cbv",
        "sha256": "d1fe221cda73ede12acdc23dc0fa4c922962b62d00ba88381f7085c3e0620902",
        "rights": "test_only_redistribution_uncleared",
    },
    "cotswold_pgn": {
        "relative": "chessit/cotswold_2023.pgn",
        "url": "https://www.chessit.co.uk/Congresses/Cotswold/2023/Cotswold_Open_2023.pgn",
        "sha256": "3053909b99d30e4d430995553b0b9db4f131c5518fa50d62167c1f0fae5bfe34",
        "rights": "test_only_redistribution_uncleared",
    },
    "twic_cbv": {
        "relative": "extracted/twic1665c6/twic1665.cbv",
        "url": "https://theweekinchess.com/zips/twic1665c6.zip",
        "sha256": "f483fa2183387643963e7a1443cb159adbfe2b0605bc1b1f7d15228b3a5b8327",
        "rights": "personal_use_only_all_rights_reserved",
    },
    "alekhine_pgn": {
        "relative": "extracted/alekhine/Alekhine.pgn",
        "url": "https://www.pgnmentor.com/players/Alekhine.zip",
        "sha256": "d3fd8dcd9fb308d7636856c6538b386191f87738d8908ebe85fa064f48b5a8a0",
        "rights": "free_download_redistribution_unclear",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_file(root: Path, key: str) -> tuple[Path, dict[str, str]]:
    metadata = SOURCES[key]
    path = root / metadata["relative"]
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"missing or indirect Section 37 source: {path}")
    observed = _sha256(path)
    if observed != metadata["sha256"]:
        raise RuntimeError(f"SHA-256 mismatch for {key}: {observed}")
    return path, metadata


def _pgn_readback(path: Path) -> dict[str, object]:
    games = parse_pgn_text(path.read_bytes().decode("utf-8-sig"), strict=False)
    results: dict[str, int] = {}
    for game in games:
        results[game.result] = results.get(game.result, 0) + 1
    return {
        "games": len(games),
        "warnings": sum(bool(game.warnings) for game in games),
        "results": dict(sorted(results.items())),
    }


def _cbv_manifest(path: Path) -> dict[str, object]:
    probe = probe_chessbase_source(path)
    manifest = build_chessbase_manifest(path)
    return {
        "probe": {
            "recognized": probe.recognized,
            "family_name": probe.family_name,
            "source_kind": probe.source_kind,
            "status": probe.status,
            "decoder_available": probe.decoder_available,
        },
        "manifest": manifest.as_dict(),
    }


def _external_cbv_readback(
    *,
    cbv: Path,
    pgn_count: int,
    uncbv: Path,
    uncbv_sha256: str,
    bridge: Path,
) -> dict[str, object]:
    extractor = ExternalCbvExtractorConfig(
        uncbv,
        expected_backend_sha256=uncbv_sha256,
        timeout_seconds=300,
        max_source_bytes=64 * 1024 * 1024,
        max_extracted_bytes=256 * 1024 * 1024,
    )
    decoder = ExternalChessBaseDecoderConfig(
        bridge,
        expected_backend_commit=LIBCBH_COMMIT,
        timeout_seconds=120,
        library_directory=bridge.parent,
    )
    with tempfile.TemporaryDirectory(prefix="accessible-chess-section37-") as temporary:
        database_path = Path(temporary) / "section37.acsdb"
        with AcsDatabase(database_path) as database:
            report = ChessBaseLibraryImportService(
                database, decoder, extractor
            ).import_database(cbv)
            if report.decoded_game_count != pgn_count:
                raise RuntimeError(
                    "CBV decoded count differs from independent PGN oracle: "
                    f"{report.decoded_game_count} != {pgn_count}"
                )
            if report.imported_game_count != pgn_count:
                raise RuntimeError("CBV import count differs from decoded count")
            if report.warnings:
                raise RuntimeError(f"CBV readback emitted warnings: {report.warnings}")
            return {
                "status": "PASS",
                "source_format": report.source_format,
                "decoded_games": report.decoded_game_count,
                "imported_games": report.imported_game_count,
                "archive_backend": report.archive_backend_name,
                "archive_backend_sha256": report.archive_backend_sha256,
                "decoder_backend_commit": report.backend_commit,
                "oracle": "cotswold_2023.pgn",
            }


def collect(root: Path, *, uncbv: Path | None, bridge: Path | None, require_external: bool) -> dict[str, object]:
    evidence: dict[str, object] = {
        "schema_version": 1,
        "section": 37,
        "source_policy": "read/test/redistribute are separate permissions",
        "sources": {},
        "external_backends": {
            "libcbh_commit": LIBCBH_COMMIT,
            "uncbv_commit": UNCBV_COMMIT,
            "bundled": False,
        },
    }
    cotswold_pgn, pgn_meta = _required_file(root, "cotswold_pgn")
    pgn_readback = _pgn_readback(cotswold_pgn)
    alekhine, alekhine_meta = _required_file(root, "alekhine_pgn")
    twic_cbv, twic_meta = _required_file(root, "twic_cbv")
    cotswold_cbv, cotswold_cbv_meta = _required_file(root, "cotswold_cbv")
    evidence["sources"] = {
        "cotswold_pgn": {**pgn_meta, "sha256": _sha256(cotswold_pgn), "readback": pgn_readback},
        "alekhine_pgn": {**alekhine_meta, "sha256": _sha256(alekhine), "readback": _pgn_readback(alekhine)},
        "cotswold_cbv": {**cotswold_cbv_meta, "sha256": _sha256(cotswold_cbv), "readback": _cbv_manifest(cotswold_cbv)},
        "twic_cbv": {**twic_meta, "sha256": _sha256(twic_cbv), "readback": _cbv_manifest(twic_cbv)},
    }
    if uncbv is not None or bridge is not None:
        if uncbv is None or bridge is None:
            raise RuntimeError("--uncbv and --libcbh-bridge must be supplied together")
        backend_sha = _sha256(uncbv)
        evidence["external_backends"].update({
            "uncbv_sha256": backend_sha,
            "libcbh_bridge_sha256": _sha256(bridge),
            "external_readback": _external_cbv_readback(
                cbv=cotswold_cbv,
                pgn_count=int(pgn_readback["games"]),
                uncbv=uncbv,
                uncbv_sha256=backend_sha,
                bridge=bridge,
            ),
        })
    else:
        evidence["external_backends"]["external_readback"] = {
            "status": "NOT_CONFIGURED",
            "reason": "GPL backends are build-time/test-time dependencies and are not bundled",
        }
        if require_external:
            raise RuntimeError("real CBV external readback was required but not configured")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--uncbv", type=Path)
    parser.add_argument("--libcbh-bridge", type=Path)
    parser.add_argument("--require-external", action="store_true")
    args = parser.parse_args(argv)
    report = collect(
        args.corpus_root,
        uncbv=args.uncbv,
        bridge=args.libcbh_bridge,
        require_external=args.require_external,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
