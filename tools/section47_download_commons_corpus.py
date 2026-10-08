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
from urllib.parse import unquote
import urllib.request

SOURCE = Path(__file__).resolve().parents[1] / "docs" / "media" / "section47_real_video_catalog.json"
API = "https://commons.wikimedia.org/w/api.php"
MAX_BYTES = 64 * 1024 * 1024
PINNED_ORIGINAL_SHA1 = {
    "byrne-fischer-game-century": "022b2c55b284c9586c5bee695d82af3a582b2adc",
    "joaquin-perkins-blitz": "910919c9c3f442c85d1388f85576956ee4ffa320",
}
AGENT = "AccessibleChess-Section47-OriginalQualification/1.0 (https://github.com/Oleksii-debug/Accessible-Chess)"


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
    name = entry["filename"]
    if not name.endswith(".webm") or Path(name).name != name or "/" in name or "\\" in name:
        raise OriginalError("unsafe file name")
    source = urllib.parse.urlsplit(entry["source_page"])
    if source.hostname != "commons.wikimedia.org" or source.scheme != "https":
        raise OriginalError("unsafe attribution source")
    source_title = unquote(source.path.rsplit("/", 1)[-1])
    if not source_title.startswith("File:") or not source_title.lower().endswith(".webm"):
        raise OriginalError("Commons title must be a WebM file")
    info = api_identity(source_title[len("File:"):])
    pinned = PINNED_ORIGINAL_SHA1.get(entry["video_id"])
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
        "source_page": entry["source_page"],
        "license": entry["license_id"],
        "license_url": entry["license_url"],
        "creator": entry["author"],
        "source_timestamp": info.get("timestamp"),
        "bytes": count,
        "sha1": sha1.hexdigest(),
        "sha256": sha256.hexdigest(),
        "sha1_pinned_before_download": pinned is not None,
        "original_bytes_verified": True,
        "decoded": False,
        "timecodes_seconds": [0, round(entry["duration_seconds"] / 3), round(entry["duration_seconds"] * 2 / 3), round(entry["duration_seconds"])],
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



def make_private_mp4_derivative(
    directory: Path, original: dict, *, clip_seconds: int = 12
) -> dict:
    """Real H.264/AAC QA clip derived from a verified Commons original.

    The derived asset is NOT represented as an original. CC-BY-SA rights and
    upstream attribution stay attached; never redistribute without review.
    """
    if type(clip_seconds) is not int or not 1 <= clip_seconds <= 60:
        raise OriginalError("invalid derivative clip duration")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise OriginalError("ffmpeg and ffprobe required for derived MP4")
    original_path = directory / original["filename"]
    if not original_path.is_file() or original_path.is_symlink():
        raise OriginalError("verified source original missing")
    if not original_path.name.endswith(".webm") or original_path.name != original["filename"]:
        raise OriginalError("invalid derivative source")
    current = hashlib.sha256(original_path.read_bytes()).hexdigest()
    if current != original["sha256"]:
        raise OriginalError("original source changed before MP4 transcode")
    target = directory / (original_path.stem + ".qa.mp4")
    if target.exists() or target.is_symlink():
        raise OriginalError("derivative destination exists")
    temporary = directory / ("." + original_path.stem + ".qa-temp.part")
    if temporary.exists() or temporary.is_symlink():
        raise OriginalError("temporary derivative destination exists")
    try:
        subprocess.run(
            [ffmpeg, "-nostdin", "-v", "error", "-i", str(original_path),
             "-t", str(clip_seconds), "-vf", "scale=480:-2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
             "-c:a", "aac", "-movflags", "+faststart", "-f", "mp4",
             str(temporary)],
            check=True, timeout=180, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if not temporary.is_file() or not 0 < temporary.stat().st_size <= MAX_BYTES:
            raise OriginalError("invalid derived MP4 size")
        metadata = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height",
             "-of", "json", str(temporary)],
            check=True, timeout=35, capture_output=True, text=True,
        )
        data = json.loads(metadata.stdout)
        if not data.get("streams") or data["streams"][0].get("codec_name") != "h264":
            raise OriginalError("derived video is not H264")
        sha256 = hashlib.sha256()
        with temporary.open("rb") as stream:
            for block in iter(lambda: stream.read(262144), b""):
                sha256.update(block)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "filename": target.name,
        "evidence_class": "DERIVED_PRIVATE_MP4",
        "video_codec": "h264",
        "derived_from_original_sha256": original["sha256"],
        "source_page": original["source_page"],
        "creator": original["creator"],
        "license": original["license"],
        "license_url": original["license_url"],
        "derivative_license_id": original["license"],
        "derivative_license_url": original["license_url"],
        "modified": True,
        "modification": "ffmpeg H264/AAC 12-second 480-pixel educational QA clip",
        "bytes": target.stat().st_size,
        "sha256": sha256.hexdigest(),
        "source_original_bytes_verified": True,
        "chess_position_qualified": False,
        "windows_player_acceptance": "NOT_RUN",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="private empty directory")
    parser.add_argument("--decode", action="store_true")
    parser.add_argument("--derive-mp4", action="store_true", help="private H264 QA clip from checked original")
    args = parser.parse_args()
    manifest = json.loads(SOURCE.read_text(encoding="utf-8"))
    entries = manifest["videos"]
    if len(entries) < 3 or len({e["filename"] for e in entries}) != len(entries):
        raise OriginalError("incomplete or duplicate original corpus")
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise OriginalError("destination must be empty (never overwrite user data)")
    receipts = []
    try:
        for entry in entries:
            print("Checking original: " + entry["filename"], flush=True)
            receipt = download_one(entry, directory, args.decode)
            receipts.append(receipt)
            print("SHA-256: " + receipt["sha256"], flush=True)
        derivatives = []
        if args.derive_mp4:
            source = next((item for item in receipts if item["filename"].startswith("Joaquin_Perkins")), None)
            if source is None:
                raise OriginalError("verified over-board source unavailable for derived MP4")
            derivatives.append(make_private_mp4_derivative(directory, source))
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
        "derivatives": derivatives,
    }
    (directory / "RECEIPT.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Populate the EXISTING canonical catalog schema with measured real bytes,
    # but only in this private test corpus. Do not rewrite repository data.
    receipt_by_name = {item["filename"]: item for item in receipts}
    qualified_catalog = {
        "schema_version": manifest["schema_version"],
        "videos": [
            {**item, "expected_sha256": receipt_by_name[item["filename"]]["sha256"]}
            for item in entries
        ],
    }
    (directory / "QUALIFIED_TEST_VIDEO_CATALOG.json").write_text(
        json.dumps(qualified_catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    attribution = [
        "ACCESSIBLE CHESS — PRIVATE REAL CHESS VIDEO TEST CORPUS",
        "Every original retains independent source, license and author.",
        "The H264 MP4 is a MODIFIED QA clip, not an original.",
        "",
    ]
    for item in entries:
        attribution.extend([
            item["filename"],
            "Author: " + item["author"],
            "Original: " + item["source_page"],
            "License: " + item["license_id"] + " — " + item["license_url"],
            "Original SHA-256: " + receipt_by_name[item["filename"]]["sha256"],
            "",
        ])
    for item in derivatives:
        attribution.extend([
            item["filename"] + " (MODIFIED private QA derivative)",
            "Source: " + item["source_page"],
            "Author: " + item["creator"],
            "Source and derivative license (ShareAlike): " + item["derivative_license_id"] + " — " + item["derivative_license_url"],
            "Source SHA-256: " + item["derived_from_original_sha256"],
            "Derivative SHA-256: " + item["sha256"],
            "Modification: " + item["modification"],
            "",
        ])
    (directory / "VIDEO_SOURCE_ATTRIBUTION.txt").write_text(
        "\n".join(attribution), encoding="utf-8",
    )
    (directory / "README_UA.txt").write_text(
        "Accessible Chess — реальні тестові відео.\n"
        "1. Знайдіть у програмі дію «Відкрити локальне медіа».\n"
        "2. Виберіть один із чотирьох відеофайлів WebM.\n"
        "3. Для перевірки MP4 відкрийте файл .qa.mp4, якщо його створено.\n"
        "4. Виконайте відтворення, паузу, перемотування і перевірте озвучення NVDA.\n"
        "5. Файл QUALIFIED_TEST_VIDEO_CATALOG.json містить перевірені SHA-256.\n"
        "6. Не трактуйте відео як автоматично підтверджену позицію FEN/PGN.\n"
        "7. Ліцензії та атрибуція — VIDEO_SOURCE_ATTRIBUTION.txt.\n",
        encoding="utf-8",
    )
    print("Receipt: " + str(directory / "RECEIPT.json"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OriginalError, OSError, ValueError, KeyError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print("Section 47 original qualification failed: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
