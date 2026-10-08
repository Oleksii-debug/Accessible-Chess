"""Section 46 reproducible visual baseline diff, fail closed on missing approvals.

Screenshot *capture* is not baseline approval.  In ordinary CI no official
approved baselines exist yet, so the diff state must remain NOT_QUALIFIED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


class VisualBaselineError(ValueError):
    pass


def compare_images(expected: Path, actual: Path, *, max_pixel_ratio: float = 0.005) -> dict:
    from PIL import Image, ImageChops

    if not expected.is_file() or not actual.is_file():
        raise VisualBaselineError("missing baseline or current screenshot")
    with Image.open(expected) as original, Image.open(actual) as observed:
        baseline, current = original.convert("RGB"), observed.convert("RGB")
        if baseline.size != current.size:
            raise VisualBaselineError(
                f"visual geometry changed: {baseline.size!r} versus {current.size!r}"
            )
        # Keep large 200%/wide full-page screenshot comparisons bounded.
        # A Python list of one boolean per pixel can exhaust CI RAM; image
        # operations and a 256-bin histogram stay in the native Pillow core.
        diff = ImageChops.difference(baseline, current)
        red, green, blue = diff.split()
        mask = ImageChops.lighter(red, ImageChops.lighter(green, blue))
        total_pixels = baseline.width * baseline.height
        changed_pixels = total_pixels - mask.histogram()[0]
        ratio = changed_pixels / max(1, total_pixels)
        if ratio > max_pixel_ratio:
            raise VisualBaselineError(
                f"approved visual regression: {changed_pixels}/{total_pixels} pixels, "
                f"ratio {ratio:.6f} > threshold {max_pixel_ratio:.6f}"
            )
        return {"total_pixels": total_pixels, "changed_pixels": changed_pixels, "ratio": ratio}


def qualify(capture_dir: Path, approved_dir: Path) -> dict:
    capture = json.loads((capture_dir / "quality-manifest.json").read_text(encoding="utf-8"))
    approved_manifest_file = approved_dir / "approved-baselines.json"
    if not approved_manifest_file.is_file():
        raise VisualBaselineError(
            "NO_APPROVED_BASELINES: screenshots were captured but no signed-off "
            "visual reference exists; do not call Section 46 screenshot diff PASS"
        )
    manifest = json.loads(approved_manifest_file.read_text(encoding="utf-8"))
    if (type(manifest) is not dict
        or set(manifest) != {
            "schema_version", "approved", "human_reviewed", "reviewer",
            "reviewed_at", "baseline_source_sha", "screenshots"
        }):
        raise VisualBaselineError("invalid human-approval manifest structure")
    if (manifest["schema_version"] != 1
        or manifest["approved"] is not True
        or manifest["human_reviewed"] is not True):
        raise VisualBaselineError("visual baselines lack explicit human approval")
    if (type(manifest["reviewer"]) is not str
        or not 3 <= len(manifest["reviewer"].strip()) <= 128
        or type(manifest["reviewed_at"]) is not str
        or re.fullmatch(r"\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\dZ",
                        manifest["reviewed_at"]) is None):
        raise VisualBaselineError("missing reviewer identity or UTC review date")
    baseline_sha = manifest["baseline_source_sha"]
    source_sha = capture.get("exact_source_sha")
    if (type(source_sha) is not str
        or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None
        or type(baseline_sha) is not str
        or re.fullmatch(r"[0-9a-f]{40}", baseline_sha) is None):
        raise VisualBaselineError("baseline or current exact source SHA missing")
    records = capture.get("records")
    approved = manifest["screenshots"]
    if type(records) is not list or type(approved) is not list:
        raise VisualBaselineError("incomplete screenshot manifest")
    names = [item.get("screenshot") for item in records if type(item) is dict]
    if len(names) != len(records) or len(names) != len(set(names)):
        raise VisualBaselineError("ambiguous captured screenshot inventory")
    names_approved = [item.get("name") for item in approved if type(item) is dict]
    if (len(approved) != len(names_approved)
        or len(approved) != len(set(names_approved))
        or set(names) != set(names_approved)):
        raise VisualBaselineError("captured screenshot set differs from approved inventory")
    hashes = {item["name"]: item.get("sha256") for item in approved}
    capture_hashes = {item["screenshot"]: item.get("sha256") for item in records}
    results = {}
    for name in sorted(names):
        if type(name) is not str or Path(name).name != name or not name.endswith(".png"):
            raise VisualBaselineError("unsafe screenshot member name")
        expected_hash = hashes[name]
        claimed_hash = capture_hashes[name]
        if any(
            type(h) is not str or re.fullmatch(r"[0-9a-f]{64}", h) is None
            for h in (expected_hash, claimed_hash)
        ):
            raise VisualBaselineError("missing approved or captured PNG SHA-256")
        actual = capture_dir / name
        baseline = approved_dir / name
        if not actual.is_file() or not baseline.is_file():
            raise VisualBaselineError("missing captured or approved screenshot")
        if hashlib.sha256(actual.read_bytes()).hexdigest() != claimed_hash:
            raise VisualBaselineError("capture PNG SHA-256 differs from source manifest")
        if hashlib.sha256(baseline.read_bytes()).hexdigest() != expected_hash:
            raise VisualBaselineError("approved PNG SHA-256 differs from review manifest")
        results[name] = compare_images(baseline, actual)
    return {
        "status": "PASS_APPROVED_BASELINE_COMPARISON",
        "exact_current_source_sha": source_sha,
        "approved_baseline_source_sha": baseline_sha,
        "human_reviewer": manifest["reviewer"],
        "images": results
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--approved", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = qualify(args.capture, args.approved)
    except VisualBaselineError as exc:
        print("SECTION46_BASELINE_DIFF=NOT_QUALIFIED:", str(exc))
        raise SystemExit(1)
    print(json.dumps(result, indent=2))
