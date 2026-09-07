from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.v1_runtime_bridge as bridge_module
from acs.v1_runtime_bridge import V1RuntimeBridgeCoordinator, V1RuntimeBridgeError
from acs.version2_upgrade import UserDataLayout


class V1RuntimeBridgePublicationAtomicityTests(unittest.TestCase):
    def test_candidate_change_during_settings_publish_leaves_no_v2_target(self) -> None:
        """A failed bridge must not leave a canonical V2 file published.

        The bridge validates a prepared candidate before hard-link publication and
        verifies it again afterward.  This regression forces the candidate to
        change in the narrow validation-to-link window.  Detection alone is not
        sufficient: the failed operation must roll back the link it created so a
        corrupt/stale candidate never remains at the canonical V2 pathname.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install = root / "installed"
            data = install / "data"
            data.mkdir(parents=True)
            executable = install / "AccessibleChess.exe"
            executable.write_bytes(b"MZ-test-fixture")
            (data / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 22}) + "\n",
                encoding="utf-8",
            )
            layout = UserDataLayout(root / "localappdata" / "AccessibleChess")

            real_link = os.link
            mutated = False

            def mutate_then_link(source: os.PathLike[str] | str, destination: os.PathLike[str] | str, *args, **kwargs) -> None:
                nonlocal mutated
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    not mutated
                    and destination_path == layout.settings_path
                    and source_path.name == layout.settings_name
                ):
                    source_path.write_bytes(b'{"language":"en","volume":99}\n')
                    mutated = True
                real_link(source, destination, *args, **kwargs)

            with mock.patch.object(bridge_module.os, "link", side_effect=mutate_then_link):
                with self.assertRaises(V1RuntimeBridgeError):
                    V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertTrue(mutated)
            self.assertFalse(
                layout.settings_path.exists(),
                "failed migration must not leave a canonical V2 settings file",
            )
            self.assertFalse(layout.library_path.exists())


if __name__ == "__main__":
    unittest.main()
