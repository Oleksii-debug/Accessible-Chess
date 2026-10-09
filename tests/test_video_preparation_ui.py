from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VideoPreparationUITests(unittest.TestCase):
    def test_background_queue_pause_and_history_modes_are_exposed(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "video_board_sync.js").read_text(encoding="utf-8")
        self.assertIn('id="video-file" type="file" accept="video/*" multiple', html)
        self.assertIn('id="video-prepare"', html)
        self.assertIn('id="video-prepare-cancel"', html)
        self.assertIn('name="video-history-mode" value="hold" checked', html)
        self.assertIn('name="video-history-mode" value="follow"', html)
        self.assertIn("video_sync_seek_time", html)
        self.assertIn("preparedVideoSessions", html)
        self.assertIn("this.video.paused", script)
        self.assertIn("class VideoPreparationController", script)

    def test_move_list_remains_the_canonical_output(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="moves"', html)
        self.assertIn("setText('moves',s.moves)", html)


if __name__ == "__main__":
    unittest.main()
