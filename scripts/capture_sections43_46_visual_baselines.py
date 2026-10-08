from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "web" / "index.html").resolve()
OUTPUT = ROOT / "artifacts" / "sections43-46-visual-baselines"

SCENARIOS = (
    ("light-wide-100", 1440, 1000, 1.0, ()),
    ("light-narrow-100", 900, 1000, 1.0, ()),
    ("dark-wide-125", 1440, 1000, 1.25, ("--force-dark-mode",)),
    ("high-contrast-150", 1440, 1000, 1.5, ("--force-high-contrast",)),
    ("light-wide-200", 1440, 1000, 2.0, ()),
)


def _chrome() -> Path:
    names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    candidates = (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("Chrome/Chromium is required for the visual baseline gate")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not PAGE.is_file():
        raise FileNotFoundError(PAGE)
    chrome = _chrome()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    url = PAGE.as_uri()
    for name, width, height, scale, extra in SCENARIOS:
        target = OUTPUT / f"{name}.png"
        command = [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            f"--window-size={width},{height}",
            f"--force-device-scale-factor={scale}",
            f"--screenshot={target}",
            *extra,
            url,
        ]
        if os.name != "nt":
            command.insert(2, "--no-sandbox")
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(
                f"Chrome screenshot failed for {name}: {result.stderr[-2000:]}"
            )
        if not target.is_file() or target.stat().st_size < 1000:
            raise RuntimeError(f"visual baseline {name} is missing or empty")
        records.append(
            {
                "name": name,
                "width": width,
                "height": height,
                "device_scale_factor": scale,
                "sha256": _sha256(target),
                "size_bytes": target.stat().st_size,
            }
        )
    manifest = {
        "schema_version": 1,
        "source": "web/index.html",
        "browser": chrome.name,
        "scenarios": records,
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
