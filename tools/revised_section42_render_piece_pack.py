"""Offline, reproducible PNG/WebP derivation of the source-pinned CC0 Lichess pack.

No downloader or remote SVG loader. Run in a disposable build workspace with
CairoSVG and Pillow installed. Output is release-candidate art, not a claim that
a packaged Windows binary or manual NVDA acceptance has passed.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PACK = Path("web/assets/pieces/rhosgfx")
PIECES = {color + kind + ".svg" for color in "wb" for kind in "KQRBNP"}
PINS = {"wK.svg": "a21a5ebbf3fb4923abfd4cbd2e27a1b7e65e6ea2",
            "wQ.svg": "c0af0ab868e5532eb6e471b300be14a4ea695af2",
            "wR.svg": "ba3d4e319796699e2ff2aacc7b1a8639a7771edd",
            "wB.svg": "16fc2ea40277d52a6cd0ab36e292834671283406",
            "wN.svg": "9650e7496606543f9f9ceca488c89af26f33b5e5",
            "wP.svg": "ceb32e2aa286bac4aa5581aa230d87088d9c0cdf",
            "bK.svg": "a726621988e47742852743ecc3c0d75a6f2ad80e",
            "bQ.svg": "cb352ffd1a3741bf72254ef39a9baa1571f622b2",
            "bR.svg": "5ce91a9f86301141aba7a540c4356a2138410208",
            "bB.svg": "b2aeb13166399342d5fba9f38d773f7bf6b43301",
            "bN.svg": "0bf9be862a0a65241aaa5afc0aae5a5a38b55e54",
            "bP.svg": "e97fce610f9e2dc35c14061e6e28d4a1f1da005d"}
SOURCE = "f5b261e3d8ece6f511484e398cb8d81e37735bea"
RIGHTS_BLOB = "def9deca8bceae28cf83d2074a3b09534ae88f6f"


class PiecePackError(ValueError):
    pass


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + bytes([0]) + data).hexdigest()


def qualify_sources(root: Path = ROOT) -> list[tuple[str, bytes]]:
    base = root / PACK
    manifest_path = base / "SECTION42_PROVENANCE.json"
    raw = manifest_path.read_bytes()
    if len(raw) > 32 * 1024:
        raise PiecePackError("manifest too large")
    try:
        m = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PiecePackError("malformed source manifest") from exc
    if (type(m) is not dict or m.get("id") != "rhosgfx"
        or m.get("schema") != "accessible-chess-section42-cc0-piece-pack-v1"
        or m.get("upstream_commit") != SOURCE
        or m.get("license") != "CC0-1.0"
        or m.get("original_copying_git_blob_sha1") != RIGHTS_BLOB
        or type(m.get("assets")) is not list or len(m["assets"]) != 12):
        raise PiecePackError("unqualified source manifest")
    notice = (base / "SOURCE_COPYING.md").read_bytes()
    if (git_blob(notice) != RIGHTS_BLOB
        or b"public/piece/rhosgfx" not in notice
        or b"CC0 1.0" not in notice):
        raise PiecePackError("original license evidence mismatch")
    found = []
    observed = set()
    for row in m["assets"]:
        if (type(row) is not dict
            or set(row) != {"file", "upstream_path", "git_blob_sha1", "bytes"}
            or row.get("file") not in PIECES
            or row["file"] in observed
            or row.get("upstream_path") != "public/piece/rhosgfx/" + row["file"]
            or type(row.get("bytes")) is not int
            or not 100 <= row["bytes"] <= 128 * 1024
            or row.get("git_blob_sha1") != PINS[row["file"]]
            or type(row.get("git_blob_sha1")) is not str
            or not re.fullmatch(r"[0-9a-f]{40}", row["git_blob_sha1"])):
            raise PiecePackError("invalid or duplicated original artwork entry")
        observed.add(row["file"])
        path = base / row["file"]
        if path.is_symlink() or not path.is_file():
            raise PiecePackError("missing or symlink original art")
        svg = path.read_bytes()
        if (len(svg) != row["bytes"]
            or git_blob(svg) != row["git_blob_sha1"]
            or b"<svg" not in svg.lower()
            or re.search(rb"<script|<foreignobject|<!entity|\son[a-z]+\s*=|\bhref\s*=", svg, re.I)):
            raise PiecePackError("tampered or active-content SVG")
        found.append((row["file"], svg))
    if observed != PIECES:
        raise PiecePackError("incomplete 12-piece source pack")
    return sorted(found)


def build_rasters(root: Path, output: Path) -> dict:
    import cairosvg  # optional offline build-only dependency
    from PIL import Image, ImageFile
    Image.MAX_IMAGE_PIXELS = 2_000_000
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    sources = qualify_sources(root)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for name, svg in sources:
        for size in (128, 256):
            raw_png = cairosvg.svg2png(bytestring=svg, output_width=size, output_height=size)
            with Image.open(io.BytesIO(raw_png)) as original:
                image = original.convert("RGBA")
            if image.size != (size, size) or image.getbbox() is None:
                raise PiecePackError("rasterization failed")
            stem = f"{name[:-4]}-{size}"
            for fmt, ext in (("PNG", ".png"), ("WEBP", ".webp")):
                path = output / (stem + ext)
                if fmt == "PNG":
                    image.save(path, format=fmt, optimize=True)
                else:
                    image.save(path, format=fmt, lossless=True, method=6)
                data = path.read_bytes()
                if not data or len(data) > 2_000_000:
                    raise PiecePackError("raster exceeds allowed size")
                results.append({"file":path.name,"source":name,"size":size,
                                "format":fmt.lower(),"bytes":len(data),
                                "sha256":hashlib.sha256(data).hexdigest()})
    report={"schema":"acs-section42-raster-derivation-v1","source_commit":SOURCE,
            "license":"CC0-1.0","originals":len(sources),
            "outputs":len(results),"assets":results,
            "source_only_qualification":False,"physical_nvda_verified":False}
    (output / "RASTER_RECEIPT.json").write_text(
        json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=ROOT)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build_rasters(args.root,args.output),sort_keys=True))


if __name__=="__main__":
    main()
