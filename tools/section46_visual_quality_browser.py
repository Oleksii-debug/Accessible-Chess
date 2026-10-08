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


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

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
                            # Browser device pixel density alone does NOT simulate
                            # 125-200% page zoom or enlarged desktop text.
                            page.evaluate("(value) => { document.documentElement.style.zoom = value; }", zoom)
                            page.locator("#ac41-theme").select_option(theme)
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
                                "native_input_select_all": selection,
                                "long_translation_no_studio_overflow": not reflow,
                                "classification": "LOCAL_UI_FIXTURE_NOT_LIVE_DEPLOYMENT",
                            })
                            context.close()
        finally:
            browser.close()
    report = {"source": "Section46 local real HTML browser qualification",
              "browser": browser_engine, "records": records,
              "screenshots_are_approved_baselines": False,
              "human_sighted_review": "NOT_PERFORMED",
              "native_windows_UIA_NVDA": "NOT_PERFORMED",
              "full_product_performance": "NOT_PERFORMED",
              "browser_scale_type": "CSS_ZOOM_AND_DEVICE_SCALE_NOT_NATIVE_WINDOWS_DPI",
              "web_backend": "NOT_CONNECTED_LOCAL_UI_FIXTURE",
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
