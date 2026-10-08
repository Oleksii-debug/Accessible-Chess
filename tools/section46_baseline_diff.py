"""Section 46 reproducible visual baseline diff, fail closed on missing approvals.

Screenshot *capture* is not baseline approval.  In ordinary CI no official
approved baselines exist yet, so the diff state must remain NOT_QUALIFIED.
"""
from __future__ import annotations

import argparse
import json
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
        diff = ImageChops.difference(baseline, current)
        channels = diff.split()
        dirty = [any(values) for values in zip(*(channel.getdata() for channel in channels))]
        changed_pixels = sum(dirty)
        total_pixels = baseline.width * baseline.height
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
    if manifest.get("approved") is not True or manifest.get("human_reviewed") is not True:
        raise VisualBaselineError("visual baselines lack explicit human approval")
    records = capture.get("records")
    approved_names = manifest.get("screenshots")
    if type(records) is not list or type(approved_names) is not list:
        raise VisualBaselineError("incomplete screenshot manifest")
    names = [item["screenshot"] for item in records]
    if len(names) != len(set(names)) or set(names) != set(approved_names):
        raise VisualBaselineError("captured screenshot set differs from approved inventory")
    results = {}
    for name in sorted(names):
        if Path(name).name != name or not name.endswith(".png"):
            raise VisualBaselineError("unsafe screenshot member name")
        results[name] = compare_images(approved_dir / name, capture_dir / name)
    return {"status": "PASS_APPROVED_BASELINE_COMPARISON", "images": results}


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
