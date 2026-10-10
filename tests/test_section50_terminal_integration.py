"""Terminal Section 50 cross-product qualification on the shipping composition.

The real-video and live-provider observations are immutable evidence produced by
the accepted Sections 47-49 lineage.  These tests verify that those observations
remain source-bound and that the current Version 2 release API composes the
video, canonical board/history, Stockfish switch, Books/Library and AI surfaces
without creating a second chess-state authority.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.ai_provider_gateway import AIProviderGateway, ProviderProfile, ProviderRequest
from acs.settings import Settings
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


ROOT = Path(__file__).resolve().parents[1]


def load_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": "Advisory text only"}}],
            "usage": {"total_tokens": 4},
        }).encode("utf-8")


class _Adapter:
    def snapshot(self):
        return {"screen": {"route_id": "board"}}


class _ProductApplication:
    """Minimal accepted host contract used to prove the one-object API seam."""

    def __init__(self):
        self.adapter = _Adapter()
        self.route = "board"

    def snapshot(self):
        return {
            "screen": {"route_id": self.route},
            "navigation": [
                {"route_id": "board"}, {"route_id": "library"},
                {"route_id": "books"}, {"route_id": "training"},
            ],
            "library": {"results": []},
            "books": {"document": None},
            "training": {"active": False},
        }

    def browser_command(self, area, command, payload=None):
        if area == "shell" and command.startswith("screen."):
            self.route = command.split(".", 1)[1]
        return {"kind": "state", "payload": self.snapshot()}

    def drain_events(self):
        return ()

    def record_focus(self, _token):
        return None

    def native_command(self, _value):
        return None

    def shutdown(self):
        return True


class Section50TerminalIntegrationTests(unittest.TestCase):
    def make_api(self, directory: str) -> Version2ReleaseAccessibleChessAPI:
        settings = Settings(Path(directory) / "settings.json")
        api = Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(directory) / "keymap.json",
            settings=settings,
        )
        api.bind_version2_application(_ProductApplication())
        return api

    def test_50_1_real_video_oracles_and_one_release_api_chain(self):
        catalog = load_json("docs/corpus/SECTION47_VIDEO_SOURCE_CATALOG.json")
        real = [item for item in catalog["candidates"] if item["status"].startswith("REAL_VIDEO_ORACLE_PASS_")]
        self.assertEqual(len(real), 2)
        self.assertEqual({len(item["sha256"]) for item in real}, {64})
        self.assertIn("canonical legal-move validation", catalog["verified"])
        self.assertIn("prepared timecode timeline and move-list projection", catalog["verified"])

        with tempfile.TemporaryDirectory() as directory:
            api = self.make_api(directory)
            self.assertTrue(api.video_prepare_start()["ok"])
            self.assertTrue(api.video_prepare_commit_move("e2e4", 10.0, 0.91)["ok"])
            self.assertTrue(api.video_prepare_commit_move("e7e5", 12.0, 0.92)["ok"])
            prepared = api.video_prepare_finish()
            self.assertTrue(prepared["ok"])
            self.assertEqual([item["san"] for item in prepared["timeline"]], ["e4", "e5"])
            self.assertTrue(api.video_sync_seek_time(99.0)["atHistoryEnd"])
            self.assertIn("Stockfish", api.get_state()["engineStatus"])
            self.assertTrue(callable(api.toggle_engine))
            api.v2_browser_command("shell", "screen.library", {})
            self.assertEqual(api.v2_snapshot()["screen"]["route_id"], "library")
            api.v2_browser_command("shell", "screen.books", {})
            self.assertEqual(api.v2_snapshot()["screen"]["route_id"], "books")

    def test_50_2_official_youtube_boundary_has_real_smoke_and_failure_states(self):
        evidence = load_json("docs/corpus/SECTION48_YOUTUBE_INTEGRATION_EVIDENCE.json")
        self.assertEqual(evidence["required_provider"], "YouTube IFrame Player API")
        self.assertIn(
            "provided URL opened in public browser smoke and exposed a 6-second YouTube player",
            evidence["verified"],
        )
        self.assertFalse(evidence["current_product_state"]["download_or_cache"])
        source = (ROOT / "web/youtube_iframe_adapter.js").read_text(encoding="utf-8")
        for state in ("playing", "paused", "buffering", "error", "unavailable", "autoplay-blocked"):
            self.assertIn("'" + state + "'", source)

    def test_50_3_live_mistral_is_preserved_and_unavailable_routes_are_not_invented(self):
        evidence = load_json("docs/corpus/SECTION49_PROVIDER_GATE_EVIDENCE.json")
        self.assertEqual(evidence["status"], "DONE")
        self.assertIn("authenticated Mistral model listing returned 46 models", evidence["verified"])
        self.assertIn(
            "live ministral-3b-latest chess FEN prompt returned White with usage metadata",
            evidence["verified"],
        )
        self.assertIn("at the owner's direction, no second provider API was tested in this closure run", evidence["closure"])
        self.assertFalse(evidence["drive_provider_root"]["secrets_persisted_logged_or_committed"])

    def test_50_4_provider_failure_model_output_and_restart_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            api = self.make_api(directory)
            initial = api.get_state()["fen"]
            profile = ProviderProfile("fixture", "https://provider.test/v1", "fixture-model", "SECTION50_FIXTURE_KEY")
            api.ai_gateway = AIProviderGateway({"fixture": profile}, opener=lambda *_args, **_kwargs: _Response())
            with patch.dict(os.environ, {"SECTION50_FIXTURE_KEY": "not-a-real-secret"}, clear=False):
                result = api.ai_complete("fixture", [{"role": "user", "content": "Invent a move"}])
            self.assertTrue(result["ok"])
            self.assertEqual(api.get_state()["fen"], initial, "advisory model output mutated canonical chess state")
            timeline = [
                {"uci": "e2e4", "timecode": 2.0, "confidence": 0.9},
                {"uci": "e7e5", "timecode": 4.0, "confidence": 0.9},
            ]
            self.assertTrue(api.video_session_save("section50", "owner-video.mp4", 8.0, timeline)["ok"])
            restarted = self.make_api(directory)
            loaded = restarted.video_session_get("section50")
            self.assertTrue(loaded["ok"])
            self.assertEqual([item["san"] for item in loaded["timeline"]], ["e4", "e5"])
            self.assertFalse(restarted.video_sync_load_timeline([
                {"uci": "e2e5", "timecode": 1.0, "confidence": 1.0},
            ])["ok"])

    def test_50_5_evidence_classes_and_secret_boundary_remain_locked(self):
        evidence = load_json("docs/corpus/SECTION50_CROSS_PRODUCT_EVIDENCE.json")
        self.assertEqual(evidence["section"], 50)
        self.assertEqual(evidence["state_authority"], "canonical chess core remains the only position authority; no model/video result may mutate it unchecked")
        self.assertEqual(evidence["evidence_classes"]["mock"], "TEST_ONLY_NOT_LIVE")
        self.assertEqual(evidence["evidence_classes"]["real_live_model"], "MISTRAL_PROTECTED_PASS")
        self.assertEqual(evidence["evidence_classes"]["youtube_provider"], "PUBLIC_BROWSER_SMOKE_PLUS_CONTRACT")
        self.assertFalse(evidence["credential_values_persisted"])

    def test_50_6_owner_test_build_assets_are_packaged_without_third_party_video(self):
        payload = (ROOT / "acs/version2_release_payload.py").read_text(encoding="utf-8")
        preflight = (ROOT / "acs/version2_package_preflight.py").read_text(encoding="utf-8")
        for asset in ("youtube_iframe_adapter.js", "video_board_sync.js", "ai_voice.js"):
            self.assertIn(asset, payload)
            self.assertIn(asset, preflight)
        catalog = load_json("docs/corpus/SECTION47_VIDEO_SOURCE_CATALOG.json")
        self.assertIn("remain excluded from Git", catalog["source_policy"])
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        for element in ("video-file", "youtube-player", "ai-provider-select", "ai-prompt", "moves"):
            self.assertIn('id="' + element + '"', html)


if __name__ == "__main__":
    unittest.main()
