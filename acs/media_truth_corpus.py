from __future__ import annotations

"""First-party deterministic visual truth corpus for recorded-media qualification.

This module does not recognize chess positions and owns no chess rules. It verifies
the integrity/provenance of project-authored synthetic frame assets and exposes the
manifest's expected BoardFrameEvidence through the existing BoardVisionPort shape.
Concrete recognizers can be tested against the same assets without making this
fixture adapter a production vision model.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .media_preprocess import (
    BoardFrameEvidence,
    BoardOrientation,
    FrameDisposition,
    PreprocessContractError,
    PreprocessErrorCode,
)

TRUTH_CORPUS_SCHEMA = "accessible-chess.recorded-media-truth-corpus"
TRUTH_CORPUS_VERSION = 1
TRUTH_CORPUS_LICENSE = "CC0-1.0"
MAX_CORPUS_BYTES = 256 * 1024
MAX_ASSET_BYTES = 1024 * 1024
MAX_FRAMES = 128
_ALLOWED_MANIFEST_KEYS = frozenset(
    {
        "schema",
        "version",
        "license",
        "provenance",
        "source_id",
        "source_revision",
        "source_ref",
        "duration_ms",
        "board_revision",
        "frames",
    }
)
_ALLOWED_FRAME_KEYS = frozenset(
    {
        "timestamp_ms",
        "asset",
        "sha256",
        "disposition",
        "orientation",
        "confidence",
        "observation_ref",
        "square_confidence",
    }
)


def _fail(message: str, code: PreprocessErrorCode = PreprocessErrorCode.INVALID) -> None:
    raise PreprocessContractError(message, code=code)


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            _fail("duplicate truth-corpus JSON key")
        output[key] = value
    return output


def _text(value: object, name: str, *, limit: int = 4096) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > limit:
        _fail(f"invalid truth-corpus {name}")
    if "\x00" in value or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        _fail(f"unsafe truth-corpus {name}")
    return value


def _safe_asset_path(root: Path, value: object) -> Path:
    name = _text(value, "asset path", limit=256)
    relative = Path(name)
    if relative.is_absolute() or len(relative.parts) != 1 or relative.name != name:
        _fail("truth-corpus asset path must be one relative filename")
    if relative.suffix.lower() != ".svg":
        _fail("truth-corpus assets must be SVG fixtures")
    candidate = root / relative
    if candidate.is_symlink():
        _fail("truth-corpus asset cannot be a symlink")
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise PreprocessContractError(
            "truth-corpus asset is unavailable",
            code=PreprocessErrorCode.INVALID,
        ) from exc
    if resolved.parent != resolved_root:
        _fail("truth-corpus asset escaped its root")
    return resolved


def _read_bounded(path: Path, limit: int, label: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PreprocessContractError(
            f"{label} is unavailable",
            code=PreprocessErrorCode.INVALID,
        ) from exc
    if size < 1 or size > limit:
        _fail(f"{label} size is outside safety bounds", PreprocessErrorCode.LIMIT)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PreprocessContractError(
            f"{label} cannot be read",
            code=PreprocessErrorCode.INVALID,
        ) from exc
    if len(data) != size:
        _fail(f"{label} changed while reading")
    return data


def _validate_svg(data: bytes) -> None:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PreprocessContractError(
            "truth-corpus SVG must be UTF-8",
            code=PreprocessErrorCode.INVALID,
        ) from exc
    lowered = text.lower()
    if not lowered.lstrip().startswith("<svg") or not lowered.rstrip().endswith("</svg>"):
        _fail("truth-corpus asset is not a standalone SVG")
    for forbidden in ("<script", "<foreignobject", "xlink:", "href=", "url(", "data:"):
        if forbidden in lowered:
            _fail("truth-corpus SVG contains active or external content")


@dataclass(frozen=True, slots=True)
class TruthCorpusFrame:
    timestamp_ms: int
    asset_name: str
    asset_sha256: str
    evidence: BoardFrameEvidence


class RecordedMediaTruthCorpus:
    __slots__ = (
        "root",
        "source_id",
        "source_revision",
        "source_ref",
        "duration_ms",
        "board_revision",
        "license",
        "provenance",
        "_frames",
        "_assets",
    )

    def __init__(
        self,
        *,
        root: Path,
        source_id: str,
        source_revision: str,
        source_ref: str,
        duration_ms: int,
        board_revision: str,
        license_id: str,
        provenance: str,
        frames: tuple[TruthCorpusFrame, ...],
        assets: dict[int, bytes],
    ) -> None:
        self.root = root
        self.source_id = source_id
        self.source_revision = source_revision
        self.source_ref = source_ref
        self.duration_ms = duration_ms
        self.board_revision = board_revision
        self.license = license_id
        self.provenance = provenance
        self._frames = frames
        self._assets = dict(assets)

    @classmethod
    def load(cls, root: str | Path) -> "RecordedMediaTruthCorpus":
        corpus_root = Path(root)
        manifest_path = corpus_root / "manifest.json"
        raw = _read_bounded(manifest_path, MAX_CORPUS_BYTES, "truth-corpus manifest")
        try:
            payload = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_pairs_no_duplicates,
                parse_constant=lambda value: _fail(
                    f"invalid non-finite truth-corpus number {value}"
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise PreprocessContractError(
                "truth-corpus manifest is invalid JSON",
                code=PreprocessErrorCode.INVALID,
            ) from exc
        if type(payload) is not dict or frozenset(payload) != _ALLOWED_MANIFEST_KEYS:
            _fail("truth-corpus manifest fields are invalid")
        if payload["schema"] != TRUTH_CORPUS_SCHEMA or payload["version"] != TRUTH_CORPUS_VERSION:
            _fail("unsupported truth-corpus schema/version")
        if payload["license"] != TRUTH_CORPUS_LICENSE:
            _fail("truth-corpus license must be explicit CC0-1.0")
        source_id = _text(payload["source_id"], "source_id", limit=512)
        source_revision = _text(payload["source_revision"], "source_revision", limit=512)
        source_ref = _text(payload["source_ref"], "source_ref", limit=4096)
        board_revision = _text(payload["board_revision"], "board_revision", limit=512)
        provenance = _text(payload["provenance"], "provenance", limit=4096)
        duration_ms = payload["duration_ms"]
        if type(duration_ms) is not int or duration_ms < 0:
            _fail("invalid truth-corpus duration")
        rows = payload["frames"]
        if type(rows) is not list or not rows or len(rows) > MAX_FRAMES:
            _fail("invalid truth-corpus frame list", PreprocessErrorCode.LIMIT)

        frames: list[TruthCorpusFrame] = []
        assets: dict[int, bytes] = {}
        seen_times: set[int] = set()
        previous = -1
        for row in rows:
            if type(row) is not dict or frozenset(row) != _ALLOWED_FRAME_KEYS:
                _fail("truth-corpus frame fields are invalid")
            timestamp = row["timestamp_ms"]
            if type(timestamp) is not int or timestamp < 0 or timestamp > duration_ms:
                _fail("truth-corpus frame timestamp is invalid")
            if timestamp <= previous or timestamp in seen_times:
                _fail("truth-corpus frame timestamps must be unique and increasing")
            previous = timestamp
            seen_times.add(timestamp)

            asset_path = _safe_asset_path(corpus_root, row["asset"])
            digest = _text(row["sha256"], "asset sha256", limit=64)
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                _fail("invalid truth-corpus asset SHA-256")
            raw_data = _read_bounded(
                asset_path, MAX_ASSET_BYTES, "truth-corpus asset"
            )
            data = raw_data.replace(b"\r\n", b"\n")
            if b"\r" in data:
                _fail("truth-corpus SVG has unsupported line endings")
            _validate_svg(data)
            if hashlib.sha256(data).hexdigest() != digest:
                _fail("truth-corpus asset SHA-256 mismatch")

            square_confidence = row["square_confidence"]
            if square_confidence is not None:
                if type(square_confidence) is not list or len(square_confidence) != 64:
                    _fail("truth-corpus square confidence must have 64 values")
                square_confidence = tuple(square_confidence)

            evidence = BoardFrameEvidence(
                source_id=source_id,
                source_revision=source_revision,
                timestamp_ms=timestamp,
                disposition=row["disposition"],
                orientation=row["orientation"],
                confidence=row["confidence"],
                observation_ref=row["observation_ref"],
                square_confidence=square_confidence,
            )
            frames.append(TruthCorpusFrame(timestamp, asset_path.name, digest, evidence))
            assets[timestamp] = data

        return cls(
            root=corpus_root,
            source_id=source_id,
            source_revision=source_revision,
            source_ref=source_ref,
            duration_ms=duration_ms,
            board_revision=board_revision,
            license_id=payload["license"],
            provenance=provenance,
            frames=tuple(frames),
            assets=assets,
        )

    @property
    def frames(self) -> tuple[TruthCorpusFrame, ...]:
        return self._frames

    def frame_at(self, timestamp_ms: int) -> TruthCorpusFrame:
        if type(timestamp_ms) is not int or timestamp_ms < 0:
            _fail("invalid truth-corpus timestamp")
        for frame in self._frames:
            if frame.timestamp_ms == timestamp_ms:
                return frame
        _fail("missing truth-corpus timestamp", PreprocessErrorCode.REQUEST_MISMATCH)
        raise AssertionError("unreachable")

    def asset_bytes(self, timestamp_ms: int) -> bytes:
        self.frame_at(timestamp_ms)
        return bytes(self._assets[timestamp_ms])


class TruthCorpusBoardVisionPort:
    """Offline BoardVisionPort backed only by verified first-party fixture truth."""

    def __init__(self, corpus: RecordedMediaTruthCorpus) -> None:
        if type(corpus) is not RecordedMediaTruthCorpus:
            raise TypeError("corpus must be RecordedMediaTruthCorpus")
        self.corpus = corpus
        self.revision_id = corpus.board_revision

    def observe(self, source_ref: str, timestamp_ms: int) -> BoardFrameEvidence:
        if source_ref != self.corpus.source_ref:
            _fail("truth-corpus source_ref mismatch", PreprocessErrorCode.SOURCE_MISMATCH)
        evidence = self.corpus.frame_at(timestamp_ms).evidence
        return BoardFrameEvidence(
            source_id=evidence.source_id,
            source_revision=evidence.source_revision,
            timestamp_ms=evidence.timestamp_ms,
            disposition=evidence.disposition,
            orientation=evidence.orientation,
            confidence=evidence.confidence,
            observation_ref=evidence.observation_ref,
            square_confidence=evidence.square_confidence,
        )


__all__ = [
    "RecordedMediaTruthCorpus",
    "TruthCorpusBoardVisionPort",
    "TruthCorpusFrame",
    "TRUTH_CORPUS_LICENSE",
    "TRUTH_CORPUS_SCHEMA",
    "TRUTH_CORPUS_VERSION",
]
