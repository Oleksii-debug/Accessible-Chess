"""Section 48: native YouTube host and browser adapter must reject identical hostile URLs.

These are offline security-contract tests, not a claim of live YouTube playback.
"""
import unittest

from acs.version2_media_runtime import _youtube_id


class Section48NativeYouTubeURLContract(unittest.TestCase):
    def test_approved_single_video_formats(self):
        value = "M7lc1UVf-VE"
        candidates = [
            value,
            "https://www.youtube.com/watch?v=" + value,
            "https://www.youtube.com/watch?v=" + value + "&t=60s",
            "https://m.youtube.com/watch?v=" + value,
            "https://youtu.be/" + value + "?t=5",
            "https://www.youtube.com/embed/" + value,
            "https://www.youtube-nocookie.com/embed/" + value,
            "https://www.youtube.com/shorts/" + value,
            "https://www.youtube.com/live/" + value,
        ]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self.assertEqual(_youtube_id(candidate), value)

    def test_unapproved_authorities_and_substitutions_fail_closed(self):
        valid = "M7lc1UVf-VE"
        invalid = [
            "", " " + valid, valid + " ",
            "http://www.youtube.com/watch?v=" + valid,
            "https://youtube.com.evil.example/watch?v=" + valid,
            "https://evil.example/https://www.youtube.com/watch?v=" + valid,
            "https://user:password@www.youtube.com/watch?v=" + valid,
            "https://www.youtube.com:8443/watch?v=" + valid,
            "https://www.youtube.com/watch?v=" + valid + "&v=AAAAAAAAAAA",
            "https://www.youtube.com/watch?v=" + valid + "&list=PL123",
            "https://youtu.be/" + valid + "/unexpected",
            "https://www.youtube.com/playlist?list=PL123",
            "https://www.youtube-nocookie.com/watch?v=" + valid,
            "https://www.youtube.com/watch?v=" + valid + "#source",
            "file:///C:/test.webm",
            "javascript:alert(1)",
            "https://www.youtube.com/watch?v=INVALID",
            "https://www.youtube.com/watch?v=",
            "https://www.youtube.com/watch?v=" + valid + "\r",
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    _youtube_id(candidate)

    def test_no_hidden_second_link_authority(self):
        with self.assertRaises(ValueError):
            _youtube_id("https://youtu.be/M7lc1UVf-VE/other")
        with self.assertRaises(ValueError):
            _youtube_id("https://youtube.com/watch?v=M7lc1UVf-VE&v=M7lc1UVf-VE")
        with self.assertRaises(ValueError):
            _youtube_id("https://youtube.com:badport/watch?v=M7lc1UVf-VE")


if __name__ == "__main__":
    unittest.main()
