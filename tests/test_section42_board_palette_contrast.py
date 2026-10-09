"""WCAG AA source-level visual text contrast for seven shared board themes."""
import math
import re
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/"web/index.html").read_text(encoding="utf-8")
CSS=(ROOT/"web/assets/accessible_chess_design.css").read_text(encoding="utf-8")
THEMES=("classic_wood","modern_graphite","tournament_blue",
        "light_minimal","high_contrast","blue")
TOKENS=("light","dark","piece-light","piece-dark")

def parse(source,theme):
    selector="#board-grid[data-theme="+theme+"]"
    match=re.search(re.escape(selector)+r"\{([^}]+)\}",source)
    if not match:
        raise AssertionError("missing theme "+theme)
    row=dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{3,6})",match.group(1)))
    if not all(k in row for k in TOKENS):
        raise AssertionError("missing palette token "+theme)
    # CSS #fff and #ffffff are visually identical; normalize notation.
    for key, value in row.items():
        digits=value.lstrip("#").lower()
        row[key]="#"+"".join(ch*2 for ch in digits) if len(digits)==3 else "#"+digits
    return row

def luminance(hexcolor):
    raw=hexcolor.lstrip("#")
    if len(raw)==3:
        raw="".join(c*2 for c in raw)
    values=[int(raw[i:i+2],16)/255 for i in (0,2,4)]
    channels=[c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4 for c in values]
    return channels[0]*0.2126+channels[1]*0.7152+channels[2]*0.0722

def ratio(a,b):
    bright,dark=sorted((luminance(a),luminance(b)),reverse=True)
    return (bright+0.05)/(dark+0.05)

class Section42PaletteContrastTests(unittest.TestCase):
    def test_shared_local_styles_match_live_windows_board(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                self.assertEqual(parse(HTML,theme),parse(CSS,theme))

    def test_textual_piece_fallback_and_coordinates_meet_wcag_aa(self):
        for theme in THEMES:
            colors=parse(HTML,theme)
            with self.subTest(theme=theme,color="light"):
                self.assertGreaterEqual(
                    ratio(colors["light"],colors["piece-light"]),4.5)
            with self.subTest(theme=theme,color="dark"):
                self.assertGreaterEqual(
                    ratio(colors["dark"],colors["piece-dark"]),4.5)

    def test_negative_fixture_detects_actual_classic_wood_regression(self):
        self.assertLess(ratio("#946f50","#fffdf7"),4.5)
        colors=parse(HTML,"classic_wood")
        self.assertGreaterEqual(ratio(colors["dark"],colors["piece-dark"]),4.8)

if __name__=="__main__":
    unittest.main()
