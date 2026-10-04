from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_local_profile_api import Version2ProfileAccessibleChessAPI
from acs.version2_upgrade_status_release import (
    create_version2_release_application,
    final_product_resource_sources,
)


class _Engine:
    def analyze(self, fen, multipv=5, depth=16):
        return ()

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        return None

    def close(self):
        return None


class _Runtime:
    def __init__(self) -> None:
        self.engine = _Engine()
        self.closed = False

    def provider(self):
        if self.closed:
            raise RuntimeError("test engine runtime is closed")
        return self.engine

    def close(self) -> None:
        self.engine.close()
        self.closed = True


class _SilentPlayback:
    def play(self, event, *, volume):
        return None


class LocalProfileFinalProductBindingTests(unittest.TestCase):
    def test_final_product_uses_profile_api_canonical_data_root_and_surface(self) -> None:
        runtime = _Runtime()
        application = None
        api = None
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "v2-user-data"
            try:
                api, application, composed_runtime, _native_runtime_factory = (
                    create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=_SilentPlayback(),
                        data_root=root,
                        copy_text=lambda _value: None,
                    )
                )
                self.assertIs(composed_runtime, runtime)
                self.assertIsInstance(api, Version2ProfileAccessibleChessAPI)

                initial = api.profile_snapshot()
                self.assertTrue(initial["ok"])
                self.assertFalse(initial["exists"])
                created = api.profile_create("Blind Reader", False)
                self.assertTrue(created["ok"])
                self.assertEqual(created["displayName"], "Blind Reader")
                self.assertNotIn("profile_id", created)
                self.assertNotIn("profileId", created)
                self.assertTrue((root / "profile.json").is_file())

                resources = dict(final_product_resource_sources())
                self.assertIn("V2 local profile surface", resources)
                surface = resources["V2 local profile surface"]
                self.assertIn('id = "v2-profile-dialog"', surface)
                self.assertIn('invoke("profile_repair"', surface)
                self.assertNotIn("innerHTML", surface)
            finally:
                try:
                    if application is not None:
                        application.shutdown()
                finally:
                    try:
                        if api is not None:
                            api.close_analysis()
                    finally:
                        runtime.close()
        self.assertTrue(runtime.closed)


if __name__ == "__main__":
    unittest.main()
