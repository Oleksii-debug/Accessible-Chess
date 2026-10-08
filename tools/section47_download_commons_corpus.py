#!/usr/bin/env python3
"""Section 47. Download original *Wikimedia Commons* chess WebM, never YouTube.

Produces PRIVATE disposable bytes, immutable SHA-256 receipts, and ffprobe/ffmpeg
qualification. Does not publish bytes or claim PGN/FEN frame semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

SOURCE = Path(__file__).resolve().parents[1] / "docs" / "SECTION47_48_REAL_MEDIA_CATALOG.json"
API = "https://commons.wikimedia.org/w/api.php"
MAX_BYTES = 32 * 1024 * 1024
AGENT = "AccessibleChess-Section47-OriginalQualification/1.0 (Wikimedia API)"


class OriginalError(RuntimeError):
    pass


class CommonsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urllib.parse.urlsplit(newurl)
        if url.scheme != "https" or url.hostname not in {
            "commons.wikimedia.org", "upload.wikimedia.org",
        } or url.username or url.password:
            raise OriginalError("redirect leaves approved original host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url: str):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "commons.wikimedia.org", "upload.wikimedia.org",
    } or parsed.username or parsed.password or parsed.port:
        raise OriginalError("untrusted original URL")
    opener = urllib.request.build_opener(CommonsOnlyRedirect)
    return opener.open(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=45)


def api_identity(name: str) -> dict:
    args = urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": 2,
        "titles": "File:" + name, "prop": "imageinfo",
        "iiprop": "url|sha1|size|mime|timestamp",
    })
    with open_url(API + "?" + args) as response:
        raw = response.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise OriginalError("metadata response too large")
    parsed = json.loads(raw)
    pages = parsed.get("query", {}).get("pages", [])
    if len(pages) != 1 or len(pages[0].get("imageinfo", [])) != 1:
        raise OriginalError("original file metadata missing or ambiguous")
    info = pages[0]["imageinfo"][0]
    if info.get("mime") != "video/webm":
        raise OriginalError("unexpected media type")
    if type(info.get("size")) is not int or not 0 < info["size"] <= MAX_BYTES:
        raise OriginalError("invalid or oversized media")
    if type(info.get("sha1")) is not str or len(info["sha1"]) != 40:
        raise OriginalError("missing original SHA-1")
    if not all(c in "0123456789abcdef" for c in info["sha1"].lower()):
        raise OriginalError("malformed original SHA-1")
    return info


def download_one(entry: dict, directory: Path, decode: bool) -> dict:
    name = entry["file"]
    if not name.endswith(".webm") or Path(name).name != name or "/" in name or "\\" in name:
        raise OriginalError("unsafe file name")
    source = urllib.parse.urlsplit(entry["page"])
    if source.hostname != "commons.wikimedia.org" or source.scheme != "https":
        raise OriginalError("unsafe attribution source")
    info = api_identity(name)
    pinned = entry.get("expected_sha1")
    if pinned is not None and pinned.lower() != info["sha1"].lower():
        raise OriginalError("Wikimedia source revision differs from pinned SHA-1")
    final = directory / name
    # Never overwrite an existing external/user file.
    if final.exists() or final.is_symlink():
        raise OriginalError("destination already exists: " + name)
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    fd, temporary = tempfile.mkstemp(prefix=".section47-", suffix=".part", dir=directory)
    count = 0
    try:
        with os.fdopen(fd, "wb") as destination, open_url(info["url"]) as response:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_BYTES or count > info["size"]:
                    raise OriginalError("original exceeds declared source size")
                sha1.update(chunk)
                sha256.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if count != info["size"] or sha1.hexdigest() != info["sha1"].lower():
            raise OriginalError("original bytes disagree with Wikimedia API identity")
        if pinned is not None and sha1.hexdigest() != pinned.lower():
            raise OriginalError("original does not match pinned SHA-1")
        with open(temporary, "rb") as probe:
            if probe.read(4) != b"\x1a\x45\xdf\xa3":
                raise OriginalError("not an EBML/WebM original")
        os.replace(temporary, final)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    result = {
        "filename": name,
        "source_page": entry["page"],
        "license": entry["license"],
        "creator": entry["creator"],
        "source_timestamp": info.get("timestamp"),
        "bytes": count,
        "sha1": sha1.hexdigest(),
        "sha256": sha256.hexdigest(),
        "sha1_pinned_before_download": pinned is not None,
        "original_bytes_verified": True,
        "decoded": False,
        "timecodes_seconds": entry["expected_timecodes_seconds"],
        "chess_position_qualified": False,
    }
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        report = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name,width,height:format=duration", "-of", "json", str(final)],
            capture_output=True, text=True, timeout=35, check=True)
        metadata = json.loads(report.stdout)
        if not metadata.get("streams"):
            raise OriginalError("ffprobe found no video stream")
        result["probe"] = metadata
    else:
        result["probe"] = "FFPROBE_NOT_AVAILABLE"
    if decode:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise OriginalError("ffmpeg not installed; no decode qualification")
        subprocess.run(
            [ffmpeg, "-nostdin", "-v", "error", "-i", str(final), "-f", "null", "-"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=150, check=True)
        result["decoded"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="private empty directory")
    parser.add_argument("--decode", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(SOURCE.read_text(encoding="utf-8"))
    entries = manifest["originals"]
    if len(entries) < 3 or len({e["file"] for e in entries}) != len(entries):
        raise OriginalError("incomplete or duplicate original corpus")
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise OriginalError("destination must be empty (never overwrite user data)")
    receipts = []
    try:
        for entry in entries:
            print("Checking original: " + entry["file"], flush=True)
            receipt = download_one(entry, directory, args.decode)
            receipts.append(receipt)
            print("SHA-256: " + receipt["sha256"], flush=True)
    except Exception:
        print("Original qualification FAILED; partial files are not a passing library.", file=sys.stderr)
        raise
    result = {
        "schema": "accessible-chess.section47-original-qualification.v1",
        "evidence_class": "EXTERNAL_ORIGINAL_BYTES",
        "count": len(receipts),
        "all_original_bytes_verified": True,
        "all_decoded": all(v["decoded"] for v in receipts),
        "board_pgn_fen_qualification": "NOT_RUN",
        "windows_player_acceptance": "NOT_RUN",
        "receipts": receipts,
    }
    (directory / "RECEIPT.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Receipt: " + str(directory / "RECEIPT.json"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OriginalError, OSError, ValueError, KeyError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print("Section 47 original qualification failed: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
