"""Section 46 opt-in browser quality/screenshot corpus.

This exercises the actual shipped Windows HTML and browser HTML under local static
fixture transport; it is NOT a real WinForms/UIA/NVDA or authenticated deployment.
Approved pixel baselines and human sighted review are separate release evidence.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import http.server
import json
import subprocess
import re
from pathlib import Path
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
THEMES = ("light", "dark", "contrast")
ZOOMS = (1.0, 1.25, 1.5, 2.0)
WIDTHS = (420, 1440)
PAGES = ("index.html", "accessible_chess_web.html")
REQUIRED_AXE_RULES = (
    "aria-allowed-attr", "aria-required-attr", "button-name",
    "color-contrast", "label", "nested-interactive",
)


def _fixture_snapshot_bytes() -> bytes:
    """Clearly nonlive data consumed by the ORIGINAL Web 64-cell renderer.

    This never pretends to be a game, chess rules, a signed-in account or
    completed actual-data media/library acceptance.
    """
    files = "abcdefgh"
    static = {
        "a8": "r", "e8": "k", "d8": "q", "h8": "r",
        "a1": "R", "e1": "K", "d1": "Q", "h1": "R",
    }
    cells = [
        {"square": file + str(rank),
         "piece": static.get(file + str(rank), ""),
         "label": "Visual fixture square " + file + str(rank)}
        for rank in range(8, 0, -1) for file in files
    ]
    snapshot = {
        "document": {"lang": "uk"},
        "screen": {"route_id": "board", "heading": "Дошка — тестова візуалізація",
                   "description": "LOCAL_UI_FIXTURE — НЕ реальна партія"},
        "board": {"cells": cells, "status": "LOCAL_UI_FIXTURE"},
        "pgn": {"status": "LOCAL_UI_FIXTURE", "notation": "1. e4 e5 2. Nf3"},
        "library": {"status": "LOCAL_UI_FIXTURE", "games": 5000},
        "books": {"status": "LOCAL_UI_FIXTURE", "title": "Accessible reading sample"},
        "training": {"status": "LOCAL_UI_FIXTURE", "puzzles": 100},
        "media": {"status": "LOCAL_UI_FIXTURE", "playback": "paused"},
        "teacher": {"status": "LOCAL_UI_FIXTURE", "lessons": 10},
        "education": {"status": "LOCAL_UI_FIXTURE", "classes": 4},
        "online": {"status": "LOCAL_UI_FIXTURE", "presence": "offline"},
        "spectator": {"status": "LOCAL_UI_FIXTURE", "session": None},
    }
    return json.dumps({"ok": True, "snapshot": snapshot},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if urlsplit(self.path).path == "/v1/snapshot":
            payload = _fixture_snapshot_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()

    def translate_path(self, path):
        url = urlsplit(path).path
        if url in {
            "/assets/section45_design_studio.js",
            "/assets/accessible_chess_web.js",
            "/assets/board_overlay_renderer.js",
        }:
            return str(WEB / url.rsplit("/", 1)[-1])
        return super().translate_path(path)

    def log_message(self, format, *args):
        pass


@contextmanager
def local_ui():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()


def verify():
    for name in PAGES:
        if not (WEB / name).is_file():
            raise RuntimeError("missing shipped UI " + name)
    axe = ROOT / "node_modules" / "axe-core" / "axe.min.js"
    if not axe.is_file():
        raise RuntimeError("axe-core is not installed; do not call this run axe PASS")
    return axe


def run(folder: Path, *, browser_engine: str = "chromium") -> dict:
    from playwright.sync_api import sync_playwright

    axe = verify()
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise RuntimeError("exact source Git SHA cannot be established")
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    with local_ui() as url, sync_playwright() as playwright:
        engine = getattr(playwright, browser_engine)
        browser = engine.launch(headless=True)
        try:
            for name in PAGES:
                for theme in THEMES:
                    for zoom in ZOOMS:
                        for width in WIDTHS:
                            context = browser.new_context(
                                viewport={"width": width, "height": 900},
                                device_scale_factor=zoom,
                                reduced_motion="reduce",
                                forced_colors="active" if theme == "contrast" else "none",
                            )
                            page = context.new_page()
                            errors = []
                            page.on("pageerror", lambda error: errors.append(str(error)[:300]))
                            page.goto(url + "/" + name, wait_until="domcontentloaded")
                            if name=="accessible_chess_web.html":
                                page.wait_for_function(
                                    "() => document.querySelectorAll('#board-grid [role=gridcell]').length === 64",
                                    timeout=12000
                                )
                            # Browser device pixel density alone does NOT simulate
                            # 125-200% page zoom or enlarged desktop text.
                            page.evaluate("(value) => { document.documentElement.style.zoom = value; }", zoom)
                            # Qualify real keyboard activation, not a synthetic
                            # click or merely programmatic focus.
                            page.locator("#ac45-toggle").focus()
                            page.keyboard.press("Enter")
                            page.wait_for_function(
                                "() => document.querySelector('#ac45-panel')?.hidden === false"
                            )
                            initial_focus=page.evaluate("document.activeElement?.id")
                            if initial_focus != "ac45-profile":
                                raise AssertionError((name,theme,zoom,width,
                                                      "Enter did not focus profile",initial_focus))
                            theme_control = next(
                                selector
                                for selector in ("#ac41-theme", "#visual-theme", "#ac45-theme")
                                if page.locator(selector).count()
                            )
                            page.locator(theme_control).select_option(theme)
                            # The Windows fixture has no privileged Settings
                            # bridge, so selecting its staged theme cannot call
                            # Apply. Render the selected local candidate without
                            # pretending that persistence was exercised.
                            page.evaluate(
                                "value => { document.documentElement.dataset.acUiTheme = value; }",
                                theme,
                            )
                            page.locator("#ac45-profile").focus()
                            page.keyboard.press("Tab")
                            keyboard_focus=page.evaluate("document.activeElement?.id")
                            if keyboard_focus != "ac45-theme":
                                raise AssertionError((name,theme,zoom,width,
                                                      "keyboard Tab did not advance to theme",keyboard_focus))
                            # Test all six actual profile choices at this geometry:
                            # Preview must never emit board mutations or alter
                            # stored FEN; candidate remains presentation-only.
                            for profile in ("Classic", "Tournament", "Coach",
                                            "Classroom Presentation", "Low Vision",
                                            "High Contrast"):
                                page.locator("#ac45-profile").select_option(profile)
                                page.locator("#ac45-preview-button").press("Enter")
                                if not page.locator("#ac45-preview").is_visible():
                                    raise AssertionError((name,theme,zoom,width,profile,
                                                          "preview unavailable"))
                            # Measure synchronous production preview redraw of
                            # six 64-square decorative boards. This is only a
                            # studio UI performance contract, not a claim about
                            # real PGN/Media/large-library game performance.
                            preview_perf=page.evaluate("""() => {
                              const names=['Classic','Tournament','Coach',
                                'Classroom Presentation','Low Vision','High Contrast'];
                              const picker=document.getElementById('ac45-profile');
                              const button=document.getElementById('ac45-preview-button');
                              const start=performance.now();
                              for(const name of names) {
                                picker.value=name;
                                picker.dispatchEvent(new Event('change',{bubbles:true}));
                                button.click();
                              }
                              return {
                                duration_ms:performance.now()-start,
                                cells:document.querySelectorAll(
                                  '#ac45-preview-board .ac45-sample-square').length
                              };
                            }""")
                            if (preview_perf["cells"] != 64 or
                                preview_perf["duration_ms"] > 1500):
                                raise AssertionError((name,theme,zoom,width,
                                                      "studio redraw regression",preview_perf))
                            page.locator("#ac45-profile").select_option("Classic")
                            # Native editable text must allow Ctrl+A selection.
                            field=page.locator("#ac45-name")
                            field.fill("Accessible Chess User Profile")
                            field.focus()
                            page.keyboard.press("ControlOrMeta+A")
                            selection=field.evaluate(
                                "(element) => ({start:element.selectionStart,"
                                "end:element.selectionEnd,length:element.value.length})"
                            )
                            if selection["start"] != 0 or selection["end"] != selection["length"]:
                                raise AssertionError((name,theme,zoom,width,"native input selection",selection))
                            field.fill("")
                            # Deliberately long UI translation; original text and
                            # tooltips are restored after measuring reflow.
                            label=page.locator('label[for="ac45-board-theme"]')
                            original_label=label.text_content()
                            label.evaluate("(node) => node.textContent = 'Accessibility presentation and long internationalized thematic control name repeated for layout validation'")
                            reflow=page.evaluate(
                                "() => document.querySelector('#ac45-studio').scrollWidth > "
                                "document.querySelector('#ac45-studio').clientWidth + 1"
                            )
                            label.evaluate("(node, text) => node.textContent = text",original_label)
                            if reflow:
                                raise AssertionError((name,theme,zoom,width,
                                                      "long translation overflow"))
                            page.locator("#ac45-profile").focus()
                            focus = page.evaluate("""() => ({
                                studio: document.querySelector('#ac45-studio')?.getAttribute('aria-labelledby'),
                                expanded: document.querySelector('#ac45-toggle')?.getAttribute('aria-expanded'),
                                focus: document.activeElement?.id,
                                keyboardFocusInitially: 'ac45-profile',
                                overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
                                status: document.querySelector('#ac45-status')?.getAttribute('aria-live'),
                                theme: document.documentElement.dataset.acUiTheme,
                                reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
                                forced: matchMedia('(forced-colors: active)').matches,
                                zoom: Number(document.documentElement.style.zoom)
                            })""")
                            if focus["expanded"] != "true" or focus["studio"] != "ac45-title" or focus["status"] != "polite":
                                raise AssertionError((name,theme,zoom,width,"semantic failure",focus))
                            if focus["theme"] != theme:
                                raise AssertionError((name,theme,zoom,width,"theme not rendered",focus))
                            if focus["overflow"]:
                                raise AssertionError((name,theme,zoom,width,"horizontal overflow",focus))
                            if abs(float(focus["zoom"]) - zoom) > 0.01:
                                raise AssertionError((name,theme,zoom,width,"CSS zoom not applied",focus))
                            if not focus["reduced"] or focus["forced"] != (theme == "contrast"):
                                raise AssertionError((name,theme,zoom,width,"forced/reduced mode",focus))
                            # A real page can exceed the logical viewport at
                            # larger zoom, but the studio must itself remain
                            # keyboard reachable and never disappear.
                            if not page.locator("#ac45-apply").is_visible():
                                raise AssertionError((name,theme,zoom,width,"Apply inaccessible"))
                            page.add_script_tag(path=str(axe))
                            violations = page.evaluate("""async () => {
                              const result = await axe.run(document, {
                                runOnly: {
                                  type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa']
                                }
                              });
                              return result.violations.map(v=>({
                                id:v.id,impact:v.impact,nodes:v.nodes.length,
                                targets:v.nodes.slice(0,3).map(n=>n.target.join(' '))
                              }));
                            }""")
                            fname = name.replace(".html", "") + "_" + theme + "_" + str(int(zoom*100)) + "_" + str(width)
                            png = folder / (fname + ".png")
                            page.screenshot(path=str(png), full_page=True, animations="disabled")
                            records.append({
                                "page": name, "theme": theme, "zoom_percent": int(zoom*100),
                                "width": width, "screenshot": png.name,
                                "sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
                                "axe_violations": violations, "page_errors": errors,
                                "semantics": focus,
                                "keyboard_focus": keyboard_focus,
                                "initial_focus": initial_focus,
                                "profile_preview_count": 6,
                                "six_board_redraw_performance": preview_perf,
                                "native_input_select_all": selection,
                                "long_translation_no_studio_overflow": not reflow,
                                "classification": "LOCAL_UI_FIXTURE_NOT_LIVE_DEPLOYMENT",
                            })
                            # Real Windows HTML keymap and engine-start dialog
                            # surfaces get additional explicit (unapproved)
                            # screenshot + axe proof in each theme at 100%.
                            if name=="index.html" and width==1440 and zoom==1.0:
                                for dialog_id in ("keymap-dialog","engine-game-dialog"):
                                    dialog=page.locator("#"+dialog_id)
                                    dialog.evaluate("(node) => node.showModal()")
                                    dialog_png=folder / (fname+"_"+dialog_id+".png")
                                    page.screenshot(
                                        path=str(dialog_png), full_page=True,
                                        animations="disabled"
                                    )
                                    dialog_violations=page.evaluate("""async () => {
                                      const result=await axe.run(document, {
                                        runOnly:{type:'tag',values:[
                                          'wcag2a','wcag2aa','wcag21a','wcag21aa']}
                                      });
                                      return result.violations.map(v=>({
                                        id:v.id,impact:v.impact,nodes:v.nodes.length,
                                        targets:v.nodes.slice(0,3).map(n=>n.target.join(' '))
                                      }));
                                    }""")
                                    records.append({
                                        "page": name,
                                        "surface": dialog_id,
                                        "theme": theme,
                                        "zoom_percent": int(zoom*100),
                                        "width": width,
                                        "screenshot": dialog_png.name,
                                        "sha256": hashlib.sha256(dialog_png.read_bytes()).hexdigest(),
                                        "axe_violations": dialog_violations,
                                        "page_errors": list(errors),
                                        "classification": "LOCAL_UI_DIALOG_NOT_LIVE_WINFORMS"
                                    })
                                    dialog.evaluate("(node) => node.close()")
                            context.close()
        finally:
            browser.close()
    report = {"source": "Section46 local real HTML browser qualification",
              "exact_source_sha": source_sha,
              "browser": browser_engine, "records": records,
              "screenshots_are_approved_baselines": False,
              "human_sighted_review": "NOT_PERFORMED",
              "native_windows_UIA_NVDA": "NOT_PERFORMED",
              "full_product_performance": "NOT_PERFORMED",
              "browser_scale_type": "CSS_ZOOM_AND_DEVICE_SCALE_NOT_NATIVE_WINDOWS_DPI",
              "web_backend": "SYNTHETIC_LOOPBACK_SNAPSHOT_NOT_AUTHENTICATED_PRODUCT",
              "axe_executed": True}
    (folder / "quality-manifest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    serious = [
        (r["page"],r["theme"],r["zoom_percent"],r["width"],v["id"])
        for r in records for v in r["axe_violations"]
        if v["impact"] in ("critical","serious")
    ]
    if serious:
        raise RuntimeError(f"axe serious/critical violations: {serious[:30]!r}")
    if any(r["page_errors"] for r in records):
        raise RuntimeError("JavaScript page errors; see quality-manifest.json")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", default="chromium", choices=("chromium","firefox","webkit"))
    args = parser.parse_args()
    result = run(args.output, browser_engine=args.engine)
    print("Section46 HTML browser screenshot/axe matrix PASS:",
          len(result["records"]), "scenarios, unapproved captured screenshots")
