"""Windows-local, noninteractive Chromium screenshot/DPI evidence for Section 43.

This is a real rendering and DOM-presence probe, not a substitute for an
external UI Automation or human NVDA acceptance. It uses the installed
Microsoft Edge binary and the actual packaged web/index.html/CSS/JS.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def edge_executable() -> Path:
    candidates = [
        shutil.which("msedge"),
        shutil.which("msedge.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value)
    raise RuntimeError("Real installed Microsoft Edge is unavailable; Windows visual smoke cannot PASS")


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 10000 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise RuntimeError(f"Missing, malformed or unexpectedly empty screenshot: {path.name}")
    width, height = struct.unpack(">II", data[16:24])
    if width < 400 or height < 240 or width > 8000 or height > 8000:
        raise RuntimeError(f"Unexpected rendered screenshot size: {path.name}: {width}x{height}")
    return width, height


def render(edge: Path, source: Path, output: Path, viewport: tuple[int, int], scale: float) -> dict:
    args = [
        str(edge), "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--hide-scrollbars",
        "--disable-extensions", "--allow-file-access-from-files",
        "--virtual-time-budget=5000",
        f"--force-device-scale-factor={scale}",
        f"--window-size={viewport[0]},{viewport[1]}",
        f"--screenshot={output}",
        source.as_uri(),
    ]
    finished = subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=60, check=False,
    )
    if finished.returncode != 0:
        raise RuntimeError(
            f"Edge headless exited {finished.returncode} ({viewport}, DPR {scale}): "
            + (finished.stderr or finished.stdout)[-1200:]
        )
    if not output.is_file():
        raise RuntimeError(f"No real screenshot produced for {viewport}, DPR {scale}")
    width, height = png_dimensions(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {
        "filename": output.name, "viewport": list(viewport), "scale": scale,
        "actual_png_dimensions": [width, height], "sha256": digest,
        "bytes": output.stat().st_size,
    }


def prove_live_dom(edge: Path, source: Path) -> None:
    result = subprocess.run(
        [str(edge), "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--disable-extensions",
         "--allow-file-access-from-files", "--virtual-time-budget=5000",
         "--dump-dom", source.as_uri()],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=60, check=False,
    )
    if result.returncode:
        raise RuntimeError("Chromium DOM execution failed: " + result.stderr[-1200:])
    for marker in (
        'id="main-content"', 'id="board-grid"',
        'id="ac43-workspace-controls"', 'id="ac43-density"',
        'id="ac43-layout"', 'data-ac43-collapsed="false"',
        'id="h-media"', 'id="h-ai-agent"',
        'id="keymap-dialog"', 'id="help-dialog"',
    ):
        if marker not in result.stdout:
            raise RuntimeError(f"Real Edge DOM bootstrap missing {marker!r}")


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("Real Windows display/Edge acceptance requires a Windows host")
    source = (ROOT / "web" / "index.html").resolve()
    if not source.is_file():
        raise RuntimeError("Packaged Stage1 HTML source is missing")
    edge = edge_executable()
    evidence_dir = ROOT / "section43-windows-visual-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    prove_live_dom(edge, source)
    cases = [
        ((1280, 800), 1.0), ((1280, 800), 1.25),
        ((1280, 800), 1.5), ((1280, 800), 2.0),
        ((800, 700), 1.0), ((1920, 1080), 1.0),
    ]
    results = []
    for viewport, scale in cases:
        file = evidence_dir / f"section43-{viewport[0]}x{viewport[1]}-{int(scale*100)}pct.png"
        results.append(render(edge, source, file, viewport, scale))
    if len({v["sha256"] for v in results}) < 3:
        raise RuntimeError("Screenshot evidence appears identical across DPI/viewport changes")
    receipt = {
        "status": "REAL_HEADLESS_WINDOWS_EDGE_RENDER_AND_DOM_PASS",
        "not_qualified": [
            "interactive Windows WebView2/UIA focus",
            "visual expert judgement",
            "physical owner/NVDA",
            "packaged executable screen rendering",
        ],
        "source": "web/index.html",
        "samples": results,
    }
    receipt_path = evidence_dir / "section43-visual-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("SECTION43_REAL_EDGE_DOM_AND_DPI_SCREENSHOTS_PASS", len(results), receipt_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
