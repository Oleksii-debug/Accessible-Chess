from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_release_app import _prepare_version2_user_data


class W2V1RuntimeBridgeCurrentStartupTests(unittest.TestCase):
    def _package(self, root: Path, *, executable: bool = True) -> Path:
        package = root / "package"
        package.mkdir()
        if executable:
            (package / "AccessibleChess.exe").write_bytes(b"MZ-current-startup-test")
        return package

    def test_packaged_executable_bridge_runs_before_canonical_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            data_root = root / "profile"
            events: list[tuple[str, Path]] = []

            class Bridge:
                def __init__(self, layout, executable):
                    self.layout = layout
                    self.executable = Path(executable)

                def run(self):
                    events.append(("bridge", self.executable))

            class Upgrade:
                def __init__(self, layout):
                    self.layout = layout

                def run(self):
                    events.append(("upgrade", self.layout.root))

            layout = _prepare_version2_user_data(
                data_root=data_root,
                application_dir=package,
                bridge_factory=Bridge,
                coordinator_factory=Upgrade,
            )

            self.assertEqual(layout.root, data_root)
            self.assertEqual(
                events,
                [
                    ("bridge", package / "AccessibleChess.exe"),
                    ("upgrade", data_root),
                ],
            )

    def test_source_or_diagnostic_root_without_executable_skips_legacy_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root, executable=False)
            data_root = root / "profile"
            events: list[str] = []

            def unexpected_bridge(*_args, **_kwargs):
                raise AssertionError("legacy bridge must not run without packaged AccessibleChess.exe")

            class Upgrade:
                def __init__(self, _layout):
                    pass

                def run(self):
                    events.append("upgrade")

            _prepare_version2_user_data(
                data_root=data_root,
                application_dir=package,
                bridge_factory=unexpected_bridge,
                coordinator_factory=Upgrade,
            )

            self.assertEqual(events, ["upgrade"])

    def test_bridge_failure_stops_before_canonical_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self._package(root)
            events: list[str] = []

            class Bridge:
                def __init__(self, _layout, _executable):
                    pass

                def run(self):
                    events.append("bridge")
                    raise RuntimeError("synthetic bridge failure")

            class Upgrade:
                def __init__(self, _layout):
                    events.append("upgrade-created")

                def run(self):
                    events.append("upgrade")

            with self.assertRaisesRegex(RuntimeError, "synthetic bridge failure"):
                _prepare_version2_user_data(
                    data_root=root / "profile",
                    application_dir=package,
                    bridge_factory=Bridge,
                    coordinator_factory=Upgrade,
                )

            self.assertEqual(events, ["bridge"])


if __name__ == "__main__":
    unittest.main()
