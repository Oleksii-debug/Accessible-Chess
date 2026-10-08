from __future__ import annotations

"""Section 47/48: real product assembly source and single native owner integration.

These are integration boundary/fixture checks, NOT a substitute for a physical
Windows WebView2/NVDA, live YouTube, or downloaded-asset qualification.
"""
from pathlib import Path
import tempfile
import unittest

from acs.media_user_workflow import MediaUserWorkflowService, MediaUserWorkflowError
from acs.version2_media_runtime import build_packaged_media_workflow
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI, _resource_sources
from acs.version2_release_payload import _REQUIRED_WEB_FILES as PAYLOAD_REQUIRED
from acs.version2_package_preflight import _REQUIRED_WEB_FILES as PREFLIGHT_REQUIRED


WEB_FILES = (
    "recorded_media_accessible_player.js",
    "local_video_playback_adapter.js",
    "youtube_iframe_playback_adapter.js",
    "version2_media_user_workflow.js",
)


class Version2MediaCompositionContract(unittest.TestCase):
    def test_production_web_scripts_load_in_canonical_order(self):
        sources = _resource_sources()
        by_label = dict(sources)
        scripts = [label for label, _ in sources]
        self.assertEqual(len(set(scripts)), len(scripts))
        self.assertIn("V2 release bootstrap", scripts)
        for label in (
            "Media accessible player",
            "Media local playback",
            "Media YouTube IFrame",
            "Media workflow",
        ):
            self.assertIn(label, by_label)
            self.assertLess(scripts.index("V2 release bootstrap"), scripts.index(label))
            self.assertTrue(by_label[label].strip())
        self.assertLess(
            scripts.index("Media local playback"),
            scripts.index("Media workflow"),
        )
        self.assertLess(
            scripts.index("Media YouTube IFrame"),
            scripts.index("Media workflow"),
        )

    def test_release_payload_really_requires_media_js(self):
        for name in WEB_FILES:
            with self.subTest(name=name):
                self.assertIn(Path("web") / name, PAYLOAD_REQUIRED)
                self.assertIn("AccessibleChess/web/" + name, PREFLIGHT_REQUIRED)

    def test_single_webview_api_reuses_accepted_media_workflow(self):
        api = object.__new__(Version2ReleaseAccessibleChessAPI)
        api._invoke_ui = lambda callback: callback()
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "fixture.webm"
            original.write_bytes(bytes.fromhex("1a45dfa3") + b"fake nondecoded test")
            service = build_packaged_media_workflow(
                open_local_path=lambda: original,
                restore_chess_ref=lambda ref: (_ for _ in ()).throw(
                    RuntimeError("unqualified ref cannot mutate chess")
                ),
                language="uk",
            )
            self.assertIs(type(service), MediaUserWorkflowService)
            api.bind_media_workflow(service)
            with self.assertRaises(RuntimeError):
                api.bind_media_workflow(service)
            local = api.media_workflow_open_local()
            self.assertEqual(local["providerKind"], "browser_local")
            self.assertTrue(local["sourceId"].startswith("local:sha256:"))
            self.assertTrue(local["browserSourceUrl"].startswith("file:///"))
            good = api.media_workflow_sync_playback(
                local["sourceId"], 1000, 15000, "playing",
            )
            self.assertEqual(good["providerKind"], "browser_local")
            with self.assertRaises(MediaUserWorkflowError):
                api.media_workflow_sync_playback("local:sha256:wrong", 5000, 15000, "playing")
            remote = api.media_workflow_open_pasted(
                "https://www.youtube.com/watch?v=M7lc1UVf-VE"
            )
            self.assertEqual(remote["providerKind"], "youtube")
            self.assertEqual(remote["sourceId"], "youtube:M7lc1UVf-VE")
            self.assertIsNone(remote.get("browserSourceUrl"))
            with self.assertRaises(MediaUserWorkflowError):
                api.media_workflow_open_pasted(
                    "https://youtube.com.evil.example/watch?v=M7lc1UVf-VE"
                )
            with self.assertRaises(MediaUserWorkflowError):
                api.media_workflow_sync_playback(
                    local["sourceId"], 100, 15000, "paused",
                )
            with self.assertRaises(MediaUserWorkflowError):
                api.media_workflow_command("restore", None)

    def test_no_unbound_browser_media_authority(self):
        api = object.__new__(Version2ReleaseAccessibleChessAPI)
        api._invoke_ui = lambda callback: callback()
        with self.assertRaises(RuntimeError):
            api.media_workflow_open_local()


if __name__ == "__main__":
    unittest.main()
