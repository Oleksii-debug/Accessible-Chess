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

    def test_in_product_playback_exposes_audio_seek_speed_and_recognition_quality(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "video_board_sync.js").read_text(encoding="utf-8")
        self.assertIn('<video id="local-video" controls', html)
        self.assertIn('id="video-seek-back"', html)
        self.assertIn('id="video-seek-forward"', html)
        self.assertIn('id="video-seek" type="range"', html)
        self.assertIn('id="video-playback-speed"', html)
        self.assertIn('id="video-recognition-quality"', html)
        self.assertIn("localVideo.muted=false", html)
        self.assertIn("video.playbackRate", html)
        self.assertIn("sampleSquare:recognitionQualitySetting()", html)
        self.assertIn("sampleSquareForVideo", script)
        self.assertIn("setSampleSquare(value)", script)


if __name__ == "__main__":
    unittest.main()
