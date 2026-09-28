from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


class Version2RemappedKeyboardNativeEditingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the shipped DOM keydown oracle")
    def test_shipped_document_keeps_native_editing_shortcuts_native(self) -> None:
        script = Path(__file__).parent / "js" / "v2_remapped_keyboard_native_editing_test.js"
        completed = subprocess.run(
            [shutil.which("node") or "node", str(script)],
            cwd=Path(__file__).parents[1],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
