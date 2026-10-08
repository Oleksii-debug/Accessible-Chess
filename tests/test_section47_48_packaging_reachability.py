"""Sections 47/48 release reachability and fail-closed payload contract."""

from html.parser import HTMLParser
from pathlib import Path
import unittest

from acs.version2_release_payload import _REQUIRED_WEB_FILES as PREPARED_WEB
from acs.version2_package_preflight import _REQUIRED_WEB_FILES as PACKAGED_WEB

ROOT = Path(__file__).resolve().parents[1]


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))


class Section47_48PackagedSurfaceContract(unittest.TestCase):
    def test_required_real_media_resources_propagate_to_actual_windows_package(self):
        originals = {
            "web/index.html",
            "web/real_media_workbench.html",
            "web/real_media_workbench.js",
            "web/youtube_iframe_playback_adapter.js",
        }
        for token in originals:
            with self.subTest(token=token):
                self.assertIn(Path(token), PREPARED_WEB)
                self.assertIn("AccessibleChess/" + token, PACKAGED_WEB)
                self.assertTrue((ROOT / token).is_file())

    def test_stage1_document_links_to_media_surface_with_a_real_href(self):
        html = _Tags()
        html.feed((ROOT / "web/index.html").read_text(encoding="utf-8"))
        self.assertTrue(any(
            tag == "a" and attrs.get("id") == "open-real-chess-video" and
            attrs.get("href") == "real_media_workbench.html"
            for tag, attrs in html.nodes
        ))

    def test_media_page_links_back_and_loads_only_approved_provider_adapter(self):
        html = _Tags()
        html.feed((ROOT / "web/real_media_workbench.html").read_text(encoding="utf-8"))
        self.assertTrue(any(tag == "a" and attrs.get("href") == "index.html"
                            for tag, attrs in html.nodes))
        self.assertTrue(any(tag == "video" and "controls" in attrs
                            and attrs.get("id") == "real-media-video"
                            for tag, attrs in html.nodes))
        scripts = [attrs.get("src") for tag, attrs in html.nodes
                   if tag == "script" and attrs.get("src")]
        self.assertEqual(scripts, [
            "youtube_iframe_playback_adapter.js",
            "real_media_workbench.js",
        ])
        self.assertTrue(any(tag == "p" and attrs.get("id") == "real-youtube-time"
                            and attrs.get("aria-live") == "off"
                            for tag, attrs in html.nodes))
        self.assertTrue(any(tag == "p" and attrs.get("id") == "real-media-time"
                            and attrs.get("aria-live") == "off"
                            for tag, attrs in html.nodes))
        for target in (
            "real-media-read-position",
            "real-youtube-read-position",
        ):
            self.assertTrue(any(tag == "button" and attrs.get("id") == target
                                for tag, attrs in html.nodes))

    def test_accepted_youtube_player_does_not_supply_undocumented_raw_media(self):
        js = (ROOT / "web/youtube_iframe_playback_adapter.js").read_text(
            encoding="utf-8").lower()
        for forbidden in ("googlevideo.", "/videoplayback", "get_video_info",
                          "dash.mpd", ".m3u8"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, js)


if __name__ == "__main__":
    unittest.main()
