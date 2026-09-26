from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "tests" / "js" / "p0g_event_aware_announcement_test.js"


class P0GAccessibleResultsReleaseQualificationTests(unittest.TestCase):
    def test_canonical_event_aware_result_oracle_passes(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(
            node,
            "Node.js is required for release qualification; the canonical P0-G JS oracle must execute",
        )

        result = subprocess.run(
            [node, str(ORACLE)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        self.assertIn("P0-G EVENT-AWARE ANNOUNCEMENT PASS", result.stdout)

    def test_release_oracle_remains_bound_to_shipping_web_document(self) -> None:
        text = ORACLE.read_text(encoding="utf-8")
        self.assertIn("web', 'index.html", text)
        self.assertIn("shipping inline script must exist", text)
        self.assertIn("two distinct user actions must remain two accessible result events", text)
        self.assertIn("rapid distinct user results must be serialized without cancellation", text)
        self.assertIn("same explicit event must stay deduplicated beyond the passive 500 ms window", text)


if __name__ == "__main__":
    unittest.main()
