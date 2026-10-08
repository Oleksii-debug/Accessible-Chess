from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1]
ADAPTER = ROOT / "web" / "youtube_iframe_adapter.js"
INDEX = ROOT / "web" / "index.html"


class YouTubeAdapterContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ADAPTER.read_text(encoding="utf-8")
        cls.index = INDEX.read_text(encoding="utf-8")

    def test_uses_official_iframe_api_and_no_media_download(self):
        self.assertIn("https://www.youtube.com/iframe_api", self.source)
        self.assertNotIn("youtube-dl", self.source.lower())
        self.assertNotIn("download =", self.source)
        self.assertNotIn("localStorage", self.source)
        self.assertNotIn("caches.open", self.source)

    def test_restricts_hosts_and_video_id_shape(self):
        for host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
            self.assertIn(host, self.source)
        self.assertRegex(self.source, re.compile(r"\[A-Za-z0-9_-\]\{11\}"))

    def test_bounded_accessible_states_are_exposed(self):
        for state in ("loading", "ready", "playing", "paused", "buffering", "ended", "error", "unavailable", "autoplay-blocked"):
            self.assertIn("'" + state + "'", self.source)
        self.assertIn("class YouTubePlayerAdapter", self.source)

    def test_ui_has_youtube_and_local_import_paths(self):
        for token in ("video-source-url", "video-load-youtube", "video-file", "local-video", "youtube-player", "video-capture-frame", "video-frame-canvas"):
            self.assertIn(token, self.index)
        self.assertIn('accept="video/*"', self.index)
        self.assertIn('youtube_iframe_adapter.js', self.index)


if __name__ == "__main__":
    unittest.main()
