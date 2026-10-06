from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "w4-v2-p0-candidate-artifact-readback.yml"
SOUND_VERIFIER = ROOT / "scripts" / "verify_w4_sound_inventory.py"
SOUND_VERIFIER_BLOB = "43b018ce6f7954e795b979658044394c7acb3532"


class W4SoundInventoryWorkflowBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_pins_exact_sound_verifier_blob(self) -> None:
        actual = subprocess.run(
            ["git", "rev-parse", "HEAD:scripts/verify_w4_sound_inventory.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(SOUND_VERIFIER_BLOB, actual)
        self.assertIn(
            f"W4_SOUND_INVENTORY_VERIFIER_BLOB_SHA: {SOUND_VERIFIER_BLOB}",
            self.text,
        )
        self.assertIn(
            'HEAD:scripts/verify_w4_sound_inventory.py',
            self.text,
        )
        self.assertIn(
            'test "$sound_blob" = "$W4_SOUND_INVENTORY_VERIFIER_BLOB_SHA"',
            self.text,
        )

    def test_workflow_reproves_and_executes_sound_byte_binding(self) -> None:
        self.assertIn(
            "cp .w4-readback-source/scripts/verify_w4_sound_inventory.py "
            ".w4-product-source/scripts/verify_w4_sound_inventory.py",
            self.text,
        )
        self.assertIn(
            'copied_sound_blob="$(git hash-object .w4-product-source/scripts/verify_w4_sound_inventory.py)"',
            self.text,
        )
        self.assertIn(
            'test "$copied_sound_blob" = "$W4_SOUND_INVENTORY_VERIFIER_BLOB_SHA"',
            self.text,
        )
        self.assertIn(
            "python .w4-product-source/scripts/verify_w4_sound_inventory.py",
            self.text,
        )
        self.assertIn(
            "--product-sha '${{ steps.product.outputs.product_sha }}'",
            self.text,
        )
        self.assertIn(
            "--workflow-sha '${{ github.event.workflow_run.head_sha }}'",
            self.text,
        )
        self.assertIn("W4_SOUND_INVENTORY_BYTE_BINDING=PASS", self.text)

    def test_sound_byte_binding_runs_before_general_current_schema_readback(self) -> None:
        sound_index = self.text.index(
            "python .w4-product-source/scripts/verify_w4_sound_inventory.py"
        )
        current_index = self.text.index(
            "python .w4-product-source/scripts/verify_w4_current_candidate_artifact.py"
        )
        self.assertLess(sound_index, current_index)


if __name__ == "__main__":
    unittest.main()
