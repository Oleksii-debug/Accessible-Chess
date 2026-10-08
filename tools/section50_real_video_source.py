"""Section 50 actual approved chess-video acquisition/decode evidence.

Uses existing lawful catalog and never redistributes video bytes. Source-byte and
frame-decode evidence is NOT board/FEN/Stockfish/Agent semantic verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

from acs.local_video_library import (
    RealVideoEntry, load_real_video_catalog, sha256_file,
)

MAX_VIDEO_BYTES = 32 * 1024 * 1024


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _download_bounded(entry: RealVideoEntry, output: Path) -> tuple[int, str]:
    if not entry.download_url.startswith("https://upload.wikimedia.org/"):
        raise ValueError("noncanonical media origin")
    # Disable ambient proxy config and HTTP redirects. HTTPS/TLS verification
    # uses stdlib defaults. Origin and source license come from checked catalog.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _RejectRedirects(),
    )
    request = urllib.request.Request(
        entry.download_url,
        headers={"User-Agent": "AccessibleChessMediaQualification/1.0 (public GitHub QA)",
                 "Accept": "video/webm,video/mp4,application/octet-stream"},
        method="GET",
    )
    size = 0
    digest = hashlib.sha256()
    with opener.open(request, timeout=30) as upstream, output.open("xb") as file:
        advertised = upstream.headers.get("Content-Length")
        if advertised is not None:
            if not advertised.isascii() or not advertised.isdigit():
                raise ValueError("invalid media Content-Length")
            if int(advertised) > MAX_VIDEO_BYTES:
                raise ValueError("video exceeds input limit")
        while True:
            chunk = upstream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_VIDEO_BYTES:
                raise ValueError("video exceeds bounded acquisition limit")
            digest.update(chunk)
            file.write(chunk)
    if size == 0:
        raise ValueError("empty video")
    if size != output.stat().st_size:
        raise ValueError("inconsistent local video size")
    prefix = output.open("rb").read(16)
    if output.suffix.lower() == ".webm":
        if not prefix.startswith(bytes.fromhex("1a45dfa3")):
            raise ValueError("not WebM")
    elif output.suffix.lower() == ".mp4":
        if b"ftyp" not in prefix:
            raise ValueError("not MP4")
    else:
        raise ValueError("unapproved video extension")
    checksum = digest.hexdigest()
    if sha256_file(output, max_bytes=MAX_VIDEO_BYTES) != checksum:
        raise ValueError("media file changed after download")
    if entry.expected_sha256 is not None and entry.expected_sha256 != checksum:
        raise ValueError("expected catalog SHA-256 mismatch")
    return size, checksum


def _decode_one_frame(source: Path, work: Path) -> tuple[str, float]:
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg/ffprobe not available")
    meta = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height",
         "-of", "json", str(source)],
        capture_output=True, check=False, timeout=40,
    )
    if meta.returncode or len(meta.stdout) > 65536:
        raise ValueError("media metadata decoding failed")
    doc = json.loads(meta.stdout)
    if type(doc) is not dict or type(doc.get("format")) is not dict:
        raise ValueError("invalid ffprobe metadata")
    duration = float(doc["format"]["duration"])
    if not 0 < duration < 86400:
        raise ValueError("invalid decoded duration")
    tracks = doc.get("streams")
    if type(tracks) is not list or not any(
        type(x) is dict and x.get("codec_type") == "video"
        and type(x.get("width")) is int and 1 <= x["width"] <= 4096
        and type(x.get("height")) is int and 1 <= x["height"] <= 4096
        for x in tracks
    ):
        raise ValueError("no bounded video stream")
    frame = work / "one_verified_frame.png"
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-ss", str(min(1.0, duration / 2)),
         "-i", str(source), "-frames:v", "1", "-y", str(frame)],
        capture_output=True, check=False, timeout=45,
    )
    if proc.returncode or not frame.is_file() or not 0 < frame.stat().st_size <= 8 * 1024 * 1024:
        raise ValueError("video frame extraction failed")
    if frame.open("rb").read(8) != bytes.fromhex("89504e470d0a1a0a"):
        raise ValueError("invalid extracted PNG")
    return hashlib.sha256(frame.read_bytes()).hexdigest(), duration


def qualify_one(entry: RealVideoEntry) -> dict[str, object]:
    report: dict[str, object] = {
        "video_id": entry.video_id, "source_page": entry.source_page,
        "license_id": entry.license_id, "author": entry.author,
        "catalog_sha256_pinned": entry.expected_sha256 is not None,
        "status": "BLOCKED", "source_sha256": None,
        "decoded_frame_sha256": None, "decoded_duration_s": None,
        "chess_board_fen": "NOT_TESTED",
        "stockfish": "NOT_TESTED", "book_library": "NOT_TESTED",
        "agent": "NOT_TESTED", "restart": "NOT_TESTED",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="acs-section50-video-") as folder:
            root = Path(folder)
            downloaded = root / entry.filename
            nbytes, digest = _download_bounded(entry, downloaded)
            report["source_bytes"] = nbytes
            report["source_sha256"] = digest
            frame_sha, duration = _decode_one_frame(downloaded, root)
            report["decoded_frame_sha256"] = frame_sha
            report["decoded_duration_s"] = round(duration, 3)
            report["status"] = (
                "SOURCE_FRAME_VERIFIED_SHA_PINNED"
                if entry.expected_sha256 is not None
                else "SOURCE_FRAME_DECODED_SHA_NOT_YET_PINNED"
            )
    except Exception:
        # Raw error bodies may contain private local paths, upstream headers or
        # host exceptions; no such text goes into the durable GitHub artifact.
        report["status"] = "BLOCKED"
        report["reason"] = "VIDEO_FETCH_DECODE_OR_INTEGRITY_FAILED"
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", default="docs/media/section47_real_video_catalog.json")
    p.add_argument("--video-id", required=True)
    p.add_argument("--output", default="section50-real-video-source-evidence.json")
    p.add_argument("--confirm-acquisition", action="store_true",
                   help="explicitly permit one approved-source network download")
    args = p.parse_args(argv)
    items = load_real_video_catalog(args.catalog)
    selected = next((x for x in items if x.video_id == args.video_id), None)
    if selected is None:
        p.error("video ID is not in the approved lawful catalog")
    report = (qualify_one(selected) if args.confirm_acquisition else
              {"video_id": selected.video_id, "status": "BLOCKED",
               "reason": "ACQUISITION_NOT_AUTHORIZED"})
    report.update({"schema": "section50-real-video-source-v1",
                   "evidence_class": "REAL_VIDEO_BYTE_FRAME_ONLY",
                   "section50_done": False})
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("VIDEO_EVIDENCE=" + str(args.output))
    print("STATUS=" + report["status"])
    print("SECTION50_DONE=NO; BOARD_FEN_NOT_PROVEN")
    return 0 if report["status"].startswith("SOURCE_FRAME") else 1


if __name__ == "__main__":
    raise SystemExit(main())
