"""Section 50 media-to-chess cross-product qualification.

The module joins existing product boundaries without making video recognition
authoritative: decoded bytes prove the media source, while every proposed move
is revalidated by :class:`AccessibleChessAPI` before consumers receive a FEN.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping

from .settings import Settings
from .webapp import AccessibleChessAPI


MAX_VIDEO_BYTES = 256 * 1024 * 1024
ALLOWED_LICENSES = frozenset({"CC0-1.0", "CC-BY-3.0", "CC-BY-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0"})


class Section50Error(ValueError):
    """Stable fail-closed boundary for Section 50 qualification."""


@dataclass(frozen=True)
class MoveObservation:
    uci: str
    timecode: float
    confidence: float
    orientation: str = "white"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_VIDEO_BYTES:
                raise Section50Error("video exceeds bounded input limit")
            digest.update(chunk)
    if size == 0:
        raise Section50Error("video is empty")
    return digest.hexdigest()


def probe_video(path: Path, *, timecodes: Iterable[float] = (0.0,)) -> dict[str, Any]:
    """Decode bounded real MP4/WebM bytes and return reproducible frame hashes."""
    source = Path(path)
    if source.suffix.lower() not in {".mp4", ".webm"} or not source.is_file():
        raise Section50Error("only an existing MP4 or WebM source is accepted")
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        raise Section50Error("ffmpeg and ffprobe are required")
    checksum = _sha256(source)
    meta = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(source)],
        capture_output=True, check=False, timeout=30,
    )
    if meta.returncode or len(meta.stdout) > 65536:
        raise Section50Error("video metadata decode failed")
    try:
        document = json.loads(meta.stdout)
        duration = float(document["format"]["duration"])
        streams = document["streams"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise Section50Error("video metadata is invalid") from None
    if not 0 < duration <= 86400 or not any(
        isinstance(item, dict) and item.get("codec_type") == "video"
        and type(item.get("width")) is int and 1 <= item["width"] <= 8192
        and type(item.get("height")) is int and 1 <= item["height"] <= 8192
        for item in streams if isinstance(streams, list)
    ):
        raise Section50Error("bounded video stream is unavailable")
    frames = []
    with tempfile.TemporaryDirectory(prefix="acs-section50-") as directory:
        for index, raw in enumerate(timecodes):
            seconds = float(raw)
            if not 0 <= seconds <= duration:
                raise Section50Error("frame timecode is outside video duration")
            output = Path(directory) / f"frame-{index}.png"
            decoded = subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", str(seconds), "-i", str(source), "-frames:v", "1", "-y", str(output)],
                capture_output=True, check=False, timeout=30,
            )
            if decoded.returncode or not output.is_file() or output.read_bytes()[:8] != bytes.fromhex("89504e470d0a1a0a"):
                raise Section50Error("video frame decode failed")
            frames.append({"timecode": seconds, "sha256": _sha256(output)})
    return {"container": source.suffix.lower()[1:], "duration": duration, "source_sha256": checksum, "frames": frames}


Consumer = Callable[[str], Mapping[str, Any]]


def qualify_cross_product(
    source: Path,
    *,
    source_id: str,
    license_id: str,
    observations: Iterable[MoveObservation],
    settings_path: Path,
    consumers: Mapping[str, Consumer],
) -> dict[str, Any]:
    """Run video → canonical FEN → consumers → persisted restart qualification."""
    if not source_id.strip() or license_id not in ALLOWED_LICENSES:
        raise Section50Error("source identity or license is not approved")
    moves = tuple(observations)
    if not moves or len(moves) > 4096:
        raise Section50Error("a bounded non-empty observation set is required")
    probe = probe_video(source, timecodes=(0.0, min(float(moves[-1].timecode), 0.5)))
    api = AccessibleChessAPI("en")
    api._settings = Settings(settings_path)
    api.video_prepare_start()
    canonical = []
    for item in moves:
        if type(item) is not MoveObservation or item.orientation not in {"white", "black"}:
            api.video_prepare_cancel()
            raise Section50Error("observation orientation is invalid")
        state = api.video_prepare_commit_move(item.uci, item.timecode, item.confidence)
        if not state.get("ok"):
            api.video_prepare_cancel()
            raise Section50Error("video observation is not a canonical legal move")
        canonical.append({"uci": item.uci, "timecode": item.timecode, "confidence": item.confidence, "fen": state["fen"]})
    finished = api.video_prepare_finish()
    if not finished.get("ok"):
        raise Section50Error("canonical timeline publication failed")
    terminal_fen = canonical[-1]["fen"]
    consumer_results = {}
    for required in ("stockfish", "books", "library", "agent"):
        consumer = consumers.get(required)
        if not callable(consumer):
            raise Section50Error(f"required consumer is missing: {required}")
        started = time.perf_counter()
        try:
            value = dict(consumer(terminal_fen))
            consumer_results[required] = {"status": "PASS", "latency_ms": round((time.perf_counter() - started) * 1000, 3), **value}
        except Exception:
            consumer_results[required] = {"status": "FAIL", "latency_ms": round((time.perf_counter() - started) * 1000, 3), "error": "consumer-failed"}
            raise Section50Error(f"consumer failed: {required}") from None
    session_id = "section50-" + probe["source_sha256"][:16]
    saved = api.video_session_save(session_id, source.name, probe["duration"], api.video_sync_timeline()["timeline"])
    if not saved.get("ok"):
        raise Section50Error("video session persistence failed")
    restarted = AccessibleChessAPI("en")
    restarted._settings = Settings(settings_path)
    loaded = restarted.video_session_get(session_id)
    if not loaded.get("ok") or len(loaded["timeline"]) != len(moves):
        raise Section50Error("video session restart failed")
    activated = restarted.video_sync_load_timeline(loaded["timeline"])
    if not activated.get("ok") or restarted.video_sync_seek_time(0)["reviewCursor"] != 0:
        raise Section50Error("resume or previous-move navigation failed")
    return {
        "schema": "accessible-chess.section50-cross-product.v1",
        "evidence_class": "AUTOMATED_EXECUTABLE_CROSS_PRODUCT",
        "source": {"id": source_id, "license": license_id, **probe},
        "canonical": {"moves": canonical, "terminal_fen": terminal_fen},
        "consumers": consumer_results,
        "restart": {"status": "PASS", "session_id": session_id, "moves": len(loaded["timeline"])},
    }


__all__ = ["MoveObservation", "Section50Error", "probe_video", "qualify_cross_product"]
