from __future__ import annotations

"""Bind the packaged P0-F W2 starter Library/PGN payload to the final V2 UI.

The package qualification lineage materializes an immutable four-file W2 bundle
beside ``AccessibleChess.exe`` under ``release-content/w2-starter``.  This layer
only discovers and validates that already-qualified payload and exposes explicit
read-only PGN open actions through the existing Library surface.  It never
silently imports sample games into the user's ACSDB, never downloads content at
runtime, and does not introduce a second PGN parser or persistence authority.
"""

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import sys

from .full_product_ui_shell import UILanguage
from .pgn_document import PgnDocumentSession
from .version2_starter_content_application import Version2StarterContentApplication


_EXPECTED_FILES = frozenset(
    {"starter_uk.pgn", "stress_uk.pgn", "sample_library.acsdb", "manifest.json"}
)
_REQUIRED_PAYLOAD_FILES = ("starter_uk.pgn", "stress_uk.pgn", "sample_library.acsdb")
_STARTER_ACTION = "library.open_packaged_starter_pgn"
_STRESS_ACTION = "library.open_packaged_stress_pgn"

_LABELS = {
    UILanguage.UA: {
        "starter": "Відкрити вбудовані 240 навчальних партій",
        "stress": "Відкрити вбудований великий PGN (1200 партій)",
        "starter_opened": "Вбудовані навчальні партії відкрито.",
        "stress_opened": "Вбудований великий PGN відкрито.",
    },
    UILanguage.EN: {
        "starter": "Open the built-in 240-game starter PGN",
        "stress": "Open the built-in large PGN (1200 games)",
        "starter_opened": "Built-in starter games opened.",
        "stress_opened": "Built-in large PGN opened.",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest(root: Path) -> dict[str, object]:
    actual = {entry.name for entry in root.iterdir() if entry.is_file()}
    if actual != _EXPECTED_FILES:
        raise RuntimeError("packaged starter content file inventory is invalid")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 3:
        raise RuntimeError("packaged starter content manifest schema is invalid")
    if manifest.get("runtime_network_required") is not False:
        raise RuntimeError("packaged starter content must not require runtime network access")

    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("packaged starter content counts are unavailable")
    starter_count = counts.get("starter_games")
    stress_count = counts.get("stress_games")
    if type(starter_count) is not int or starter_count < 200:
        raise RuntimeError("packaged starter content has fewer than 200 starter games")
    if type(stress_count) is not int or stress_count <= starter_count:
        raise RuntimeError("packaged starter stress corpus is not larger than the starter corpus")

    source = manifest.get("starter_source")
    if not isinstance(source, dict) or source.get("license_id") != "CC0-1.0":
        raise RuntimeError("packaged starter source license is invalid")
    if source.get("selected_games") != starter_count:
        raise RuntimeError("packaged starter source count does not match the manifest")

    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(_REQUIRED_PAYLOAD_FILES):
        raise RuntimeError("packaged starter content payload manifest is invalid")
    for name in _REQUIRED_PAYLOAD_FILES:
        metadata = files.get(name)
        path = root / name
        if not isinstance(metadata, Mapping):
            raise RuntimeError("packaged starter content file metadata is invalid")
        expected_hash = metadata.get("sha256")
        expected_bytes = metadata.get("bytes")
        if type(expected_hash) is not str or len(expected_hash) != 64:
            raise RuntimeError("packaged starter content hash metadata is invalid")
        if type(expected_bytes) is not int or expected_bytes < 1:
            raise RuntimeError("packaged starter content byte metadata is invalid")
        if path.stat().st_size != expected_bytes or _sha256(path) != expected_hash.casefold():
            raise RuntimeError(f"packaged starter content integrity failed for {name}")
    return manifest


def _default_bundle_root() -> Path:
    return Path(sys.executable).resolve().parent / "release-content" / "w2-starter"


class Version2PackagedStarterApplication(Version2StarterContentApplication):
    """Expose qualified packaged W2 PGNs without mutating the user's Library."""

    def __init__(self, *args, packaged_starter_root: str | Path | None = None, **kwargs) -> None:
        explicit = packaged_starter_root is not None
        root = Path(packaged_starter_root) if explicit else _default_bundle_root()
        self._packaged_starter_root: Path | None = None
        self._packaged_starter_manifest: dict[str, object] | None = None
        if root.exists():
            if not root.is_dir():
                raise RuntimeError("packaged starter content root is not a directory")
            self._packaged_starter_manifest = _load_manifest(root)
            self._packaged_starter_root = root
        elif explicit:
            raise RuntimeError("packaged starter content root is missing")
        super().__init__(*args, **kwargs)

    def _starter_library_actions(self) -> tuple[dict[str, object], ...]:
        if self._packaged_starter_root is None:
            return ()
        labels = _LABELS[self.shell.language]
        return (
            {"action": _STARTER_ACTION, "label": labels["starter"], "enabled": True},
            {"action": _STRESS_ACTION, "label": labels["stress"], "enabled": True},
        )

    def _decorate_library_snapshot(self, snapshot: Mapping[str, object]) -> dict[str, object]:
        result = dict(snapshot)
        actions = list(result.get("actions", ()))
        actions.extend(self._starter_library_actions())
        result["actions"] = tuple(actions)
        manifest = self._packaged_starter_manifest
        if manifest is not None:
            counts = manifest["counts"]
            result["packaged_starter_content"] = {
                "available": True,
                "starter_games": counts["starter_games"],
                "stress_games": counts["stress_games"],
                "network_required": False,
                "prebuilt_library": True,
            }
        return result

    def _open_packaged_pgn(self, *, stress: bool) -> dict[str, object]:
        root = self._packaged_starter_root
        if root is None:
            raise ValueError("packaged starter content is unavailable")
        name = "stress_uk.pgn" if stress else "starter_uk.pgn"
        session = PgnDocumentSession.open(root / name)
        self.set_document(session)
        labels = _LABELS[self.shell.language]
        return {
            "kind": "status",
            "payload": {
                "announcement": labels["stress_opened" if stress else "starter_opened"],
                "focus_target": "pgn-game-list",
            },
        }

    def browser_command(self, area, command, payload=None):
        self._assert_thread()
        if area == "library" and command in {_STARTER_ACTION, _STRESS_ACTION}:
            try:
                if payload not in (None, {}):
                    raise ValueError("packaged starter content action accepts no payload")
                return self._open_packaged_pgn(stress=command == _STRESS_ACTION)
            except Exception:
                return self._error()
        return super().browser_command(area, command, payload)

    def snapshot(self) -> dict[str, object]:
        result = super().snapshot()
        library = result.get("library")
        if isinstance(library, Mapping):
            result["library"] = self._decorate_library_snapshot(library)
        return result


__all__ = ["Version2PackagedStarterApplication"]
