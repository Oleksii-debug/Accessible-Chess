"""Section 41 exact-source MIT Tabler asset qualification and SPDX evidence.

No external network, no dynamic npm install, no dependency auto-download, no
Pro/ApexCharts, and no claim full Windows release is accepted. Reuse canonical
acs.spdx_sbom; these are verified static UI asset components only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from acs.spdx_sbom import (
    ComponentRecord, build_spdx_document, canonical_spdx_json,
)

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = Path("web/assets/tabler/SECTION41_PROVENANCE.json")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class Section41AssetError(RuntimeError):
    pass


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def qualified_mit_icons(*, root: Path = ROOT) -> tuple[dict, tuple[ComponentRecord, ...]]:
    """Require original exact Git blob identity AND the complete MIT notice."""
    data = json.loads((root / INVENTORY).read_text(encoding="utf-8"))
    if (type(data) is not dict or
        data.get("schema") != "accessible-chess-section41-third-party-assets-v1"
        or type(data.get("prohibited")) is not list
        or not {"@tabler/pro", "apexcharts"}.issubset(data["prohibited"])):
        raise Section41AssetError("Section 41 rights and scope policy invalid")
    obj = data["release_pinning"]["tabler_icons"]
    if (obj["release_tag"] != "v3.49.0"
        or obj["commit_sha"] != "bbed884d15354b5cebf2493371f20dc2d5e83eaf"
        or obj["license"] != "MIT"
        or not SHA1_RE.fullmatch(obj["commit_sha"])):
        raise Section41AssetError("MIT Tabler Icons source pin changed")
    notice = (root / obj["license_source"]).read_bytes()
    if (git_blob_sha1(notice) != obj["original_license_blob_sha1"]
        or b"MIT License" not in notice
        or b"Permission is hereby granted" not in notice):
        raise Section41AssetError("MIT Tabler Icons original license proof failed")
    qualified = []
    rows = []
    for entry in obj["assets"]:
        if (type(entry) is not dict
            or set(entry) != {"installed", "original", "git_blob_sha1", "bytes"}
            or not str(entry["installed"]).startswith("web/assets/tabler/")
            or not str(entry["original"]).startswith("icons/outline/")
            or "/" in Path(entry["installed"]).name
            or not SHA1_RE.fullmatch(entry["git_blob_sha1"])):
            raise Section41AssetError("installed Tabler asset path invalid")
        path = root / entry["installed"]
        before = path.lstat()
        if path.is_symlink() or not path.is_file() or before.st_size != entry["bytes"]:
            raise Section41AssetError("pinned installed MIT SVG absent/indirect")
        content = path.read_bytes()
        after = path.lstat()
        if (before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or git_blob_sha1(content) != entry["git_blob_sha1"]
            or b"<script" in content.lower() or b"<!entity" in content.lower()
            or b"<foreignobject" in content.lower()
            or b"<svg" not in content.lower()):
            raise Section41AssetError("installed Tabler asset bytes are not pinned original")
        digest = hashlib.sha256(content).hexdigest()
        rows.append({"local": entry["installed"], "upstream": entry["original"],
                     "git_blob_sha1": entry["git_blob_sha1"],
                     "sha256": digest, "bytes": len(content), "license": "MIT"})
        qualified.append(ComponentRecord(
            name="Tabler Icons " + Path(entry["original"]).stem,
            version="3.49.0",
            artifact_sha256=digest,
            license_declared="MIT",
            supplier="Organization: Tabler",
            download_location="https://github.com/tabler/tabler-icons/tree/v3.49.0/icons/outline",
            copyright_text="Copyright (c) 2020-2026 Paweł Kuna",
        ))
    if len(qualified) != 2 or len({x["local"] for x in rows}) != 2:
        raise Section41AssetError("pinned Tabler icon selection changed")
    if data["release_pinning"]["tabler_core"]["integration_status"] != "REVIEWED_CSS_COMPONENT_ONLY":
        raise Section41AssetError("unreviewed complete Tabler Core import cannot be claimed")
    return {
        "schema": "acs-section41-mit-asset-evidence-v1",
        "asset_count": len(rows), "items": rows,
        "icons_upstream_commit": obj["commit_sha"],
        "tabler_core_status": "REVIEWED_CSS_COMPONENT_ONLY",
        "paid_assets_included": False,
        "nvda_human_verified": False,
        "section41_done": False,
    }, tuple(qualified)



def qualified_mit_tabler_core(*, root: Path = ROOT) -> tuple[dict, ComponentRecord]:
    """Qualify ONE reviewed standalone MIT CSS component, never the full npm UI.

    Exact original upstream Sass and original license are audited separately;
    the distributed CSS is a bounded, dependency-free derivative of those
    reviewed forced-color and reduced-motion selectors.
    """
    meta_path = root / "web/assets/tabler-core/SECTION41_CORE_PROVENANCE.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Section41AssetError("Tabler Core provenance missing/invalid") from exc
    required = {
        "release_tag": "@tabler/core@1.6.1",
        "source_commit": "ec33733290bd0f314ca19f6be58bc69a6ab3e4fa",
        "source_git_blob": "047720ee79039e213612cfbadd6af357534a7735",
        "original_license_git_blob": "aa69649cde83c2d6517ec2498a9c10f5bb3bf54c",
        "compiled_css_git_blob": "0fe8f69f90411731513c9926827fb609bf51b267",
        "upstream_license": "MIT",
    }
    if (type(data) is not dict
        or data.get("schema") != "accessible-chess-section41-reviewed-tabler-core-v1"
        or any(data.get(k) != v for k, v in required.items())
        or any(token in data.get("component_scope", ())
               for token in ("ApexCharts", "Tabler Pro"))):
        raise Section41AssetError("Tabler Core MIT source/derivative identity changed")
    # The manifest cannot redirect a checksum-verified read outside the repo,
    # even if its listed Git object digests happen to remain unchanged.
    if (data.get("source_path") != "docs/third_party/tabler-core-1.6.1-accessibility.scss"
        or data.get("license_path") != "web/assets/tabler-core/LICENSE"
        or data.get("compiled_css") != "web/assets/tabler-core/accessibility.css"):
        raise Section41AssetError("Tabler Core provenance path redirect refused")
    pinned = (
        (data["source_path"], required["source_git_blob"], 32 * 1024),
        (data["license_path"], required["original_license_git_blob"], 16 * 1024),
        (data["compiled_css"], required["compiled_css_git_blob"], 64 * 1024),
    )
    qualified = {}
    for name, expected, maximum in pinned:
        path = root / name
        if not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise Section41AssetError("Tabler Core source/compiled/notice not a regular file")
        before = path.stat()
        if not 1 <= before.st_size <= maximum:
            raise Section41AssetError("Tabler Core source/compiled/notice size invalid")
        content = path.read_bytes()
        after = path.stat()
        if (before.st_ino != after.st_ino or before.st_mtime_ns != after.st_mtime_ns
            or before.st_size != after.st_size
            or git_blob_sha1(content) != expected):
            raise Section41AssetError("Tabler Core upstream source/notice/CSS tampered")
        qualified[name] = content
    css = qualified[data["compiled_css"]]
    if (b"@import" in css or b"http://" in css or b"https://" in css
        or b"@media (forced-colors: active)" not in css
        or b"@media (prefers-reduced-motion: reduce)" not in css
        or b"<script" in css.lower()):
        raise Section41AssetError("isolated Tabler Core CSS violates local UI policy")
    notice = qualified[data["license_path"]]
    if b"MIT License" not in notice or b"Permission is hereby granted" not in notice:
        raise Section41AssetError("Tabler Core MIT notice incomplete")
    component = ComponentRecord(
        name="Tabler Core reviewed accessibility CSS",
        version="1.6.1",
        artifact_sha256=hashlib.sha256(css).hexdigest(),
        license_declared="MIT",
        supplier="Organization: Tabler",
        download_location="https://github.com/tabler/tabler/releases/tag/%40tabler%2Fcore%401.6.1",
        copyright_text="Copyright (c) 2018-2026 The Tabler Authors",
    )
    record = {
        "name": component.name, "version": component.version,
        "original_source_sha1": required["source_git_blob"],
        "original_license_sha1": required["original_license_git_blob"],
        "local_css_git_blob": required["compiled_css_git_blob"],
        "local_css_sha256": component.artifact_sha256,
        "license": "MIT",
        "use": "REVIEWED_LOCAL_CSS_ONLY_NO_BOOTSTRAP_JS",
    }
    return record, component


def build_asset_fixture_spdx(*, root: Path, exact_commit: str) -> tuple[dict, dict]:
    if not SHA1_RE.fullmatch(exact_commit):
        raise Section41AssetError("exact source Git commit unavailable")
    report, components = qualified_mit_icons(root=root)
    core_receipt, core_component = qualified_mit_tabler_core(root=root)
    report["tabler_core"] = core_receipt
    # The fixture inventory is the product of this narrow qualification run;
    # it is NOT a claim about the installed executable's content or rights.
    digest = hashlib.sha256(json.dumps(
        {"icons": report["items"], "core": core_receipt},
        sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    evidence = build_spdx_document(
        product_name="Accessible Chess Section 41 UI asset fixture (not final EXE)",
        product_version="41.0-source-fixture",
        source_sha=exact_commit,
        product_sha256=digest,
        components=(*components, core_component),
        created_at=datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc),
        product_license_declared="NOASSERTION",
    )
    return report, evidence


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report, sbom = build_asset_fixture_spdx(root=args.root, exact_commit=args.head)
    if args.output.exists() or args.output.is_symlink():
        raise Section41AssetError("refusing to overwrite design asset evidence")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "section41-icons-evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output / "section41-icons-spdx-2.3.json").write_text(
        canonical_spdx_json(sbom), encoding="utf-8",
    )
    print(json.dumps({"qualified_source_icon_count": report["asset_count"],
                      "section41_done": False, "spdx": "fixture_only"}))


if __name__ == "__main__":
    main()
