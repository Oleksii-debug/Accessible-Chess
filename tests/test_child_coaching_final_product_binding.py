from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_upgrade_status_release import create_version2_release_application


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


class ChildCoachingFinalProductBindingTests(unittest.TestCase):
    def test_release_composition_binds_child_coaching_to_canonical_data_root(self) -> None:
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
                child = application._child_coaching_application
                self.assertIsNotNone(child)
                assert child is not None
                self.assertEqual(
                    root / "child-coaching.json",
                    child.store.path,
                )
                self.assertIsNotNone(application._prepared_position_navigator)
                rotation_store = application._rotation_store
                self.assertIsNotNone(rotation_store)
                assert rotation_store is not None
                self.assertEqual(
                    root / "child-coaching-rotation.json",
                    rotation_store.path,
                )

                catalog = application.open_child_coaching_catalog()
                self.assertGreaterEqual(len(catalog.templates), 4)
                self.assertTrue((root / "child-coaching.json").is_file())
                status = application.snapshot()["product_status"]
                self.assertTrue(status["child_coaching_available"])
                self.assertTrue(status["prepared_position_navigation_available"])
                self.assertFalse(status["child_coaching_recovery_required"])
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
