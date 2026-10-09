from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


class _Contracts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.controls = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        key = attrs.get("id")
        if key in {"product-mode", "key-search-label", "key-search", "h-settings"}:
            self.controls[key] = (tag, attrs)


class Section41VendoredAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((WEB / "section41_vendor_manifest.json").read_text(encoding="utf-8"))

    def test_exact_upstream_badge_blob_and_license(self):
        data = (WEB / "tabler_badges_source.scss").read_bytes()
        self.assertEqual(_git_blob_sha1(data), self.manifest["tabler"]["original_git_blob_sha1"])
        self.assertEqual(self.manifest["tabler"]["commit"], "ec33733290bd0f314ca19f6be58bc69a6ab3e4fa")
        self.assertIn("MIT License", (WEB / "SECTION41_THIRD_PARTY_NOTICES.txt").read_text())

    def test_exact_upstream_svg_blobs_and_svg_integrity(self):
        icons = self.manifest["tabler_icons"]
        self.assertEqual(icons["commit"], "bbed884d15354b5cebf2493371f20dc2d5e83eaf")
        for icon in icons["files"]:
            with self.subTest(icon=icon["path"]):
                path = ROOT / icon["path"]
                self.assertEqual(path.parent, WEB)
                data = path.read_bytes()
                self.assertEqual(_git_blob_sha1(data), icon["original_git_blob_sha1"])
                root = ET.fromstring(data)
                self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
                self.assertEqual(root.get("viewBox"), "0 0 24 24")
                self.assertNotIn(b"<script", data.lower())
                self.assertNotIn(b"<foreignObject", data)
                self.assertNotIn(b"<script", data.lower())
                self.assertNotIn(b"xlink:href", data.lower())
                self.assertNotIn(b"<image", data.lower())

    def test_only_local_opt_in_presentation_no_chess_override(self):
        css = (WEB / "tabler_subset.css").read_text(encoding="utf-8")
        self.assertIn(".ac-tb-badge", css)
        self.assertIn(".ac-tb-search-label::before", css)
        self.assertIn(".ac-tb-settings-heading::after", css)
        self.assertIn("forced-colors: active", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertNotIn("https://", css)
        self.assertNotRegex(css, r"(?m)^\s*(?:body|button|input|select|main|\[role=gridcell\])\s*\{")
        self.assertNotIn("@import", css)
        self.assertNotIn("javascript:", css.lower())
        self.assertEqual(self.manifest["runtime_dependency_list"], [])
        self.assertFalse(self.manifest["tabler"]["bootstrap_runtime_bundled"])
        self.assertNotIn("apexcharts", css.lower())

    def test_html_accessible_native_semantics_and_offline_assets(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('<link rel="stylesheet" href="tabler_subset.css">'), 1)
        self.assertLess(html.index('href="design_system.css"'), html.index('href="tabler_subset.css"'))
        parser = _Contracts()
        parser.feed(html)
        mode, attrs = parser.controls["product-mode"]
        self.assertEqual(mode, "div")
        self.assertIn("ac-tb-badge", attrs["class"].split())
        tag, attrs = parser.controls["key-search-label"]
        self.assertEqual(tag, "label")
        self.assertEqual(attrs["for"], "key-search")
        self.assertIn("ac-tb-search-label", attrs["class"].split())
        self.assertEqual(parser.controls["key-search"][0], "input")
        self.assertEqual(parser.controls["key-search"][1]["type"], "search")
        self.assertEqual(parser.controls["h-settings"][0], "h2")
        self.assertIn("ac-tb-settings-heading", parser.controls["h-settings"][1]["class"].split())
        self.assertIn('role="status"', html)
        self.assertIn('aria-live="polite"', html)

    def test_reject_mutated_asset_or_missing_license_negative_case(self):
        item = self.manifest["tabler_icons"]["files"][0]
        data = (ROOT / item["path"]).read_bytes()
        self.assertNotEqual(_git_blob_sha1(data + b"tampered"), item["original_git_blob_sha1"])
        self.assertNotEqual(_git_blob_sha1(data[:-1]), item["original_git_blob_sha1"])
        notice = (WEB / "SECTION41_THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
        for expected in ("Tabler Authors", "Paweł Kuna", "Permission is hereby granted"):
            self.assertIn(expected, notice)


if __name__ == "__main__":
    unittest.main()
