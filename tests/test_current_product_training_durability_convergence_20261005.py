from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / ".github" / "workflows" / "current-product-training-durability-convergence.yml"
SOURCE_GATE = ROOT / ".github" / "workflows" / "training-progress-durability.yml"


class CurrentProductTrainingDurabilityConvergenceTests(unittest.TestCase):
    def test_gate_is_exact_head_dual_os_and_fail_closed(self) -> None:
        text = GATE.read_text(encoding="utf-8")
        self.assertIn("ubuntu-22.04", text)
        self.assertIn("windows-2025", text)
        self.assertIn("TRAINING_DURABILITY_CANDIDATE_SUPERSEDED", text)
        self.assertIn("TRAINING_DURABILITY_BASE_MOVED", text)
        self.assertIn("TRAINING_DURABILITY_SOURCE_MOVED", text)
        self.assertIn('test "$(git show -s --format=%P HEAD)" = "$BASE_HEAD $SOURCE_HEAD"', text)
        self.assertNotIn("continue-on-error:", text)

    def test_source_exact_candidate_guard_is_retained(self) -> None:
        text = SOURCE_GATE.read_text(encoding="utf-8")
        self.assertIn("TRAINING_PROGRESS_SUPERSEDED", text)
        self.assertIn("TRAINING_PROGRESS_EXACT_HEAD=PASS", text)
        self.assertIn("${{ github.event.pull_request.head.sha || github.sha }}", text)
        self.assertIn("converge/current-product-training-durability-evidence-20261005-zftrkmo", text)

    def test_gate_runs_persistence_recovery_and_whole_product_smoke(self) -> None:
        text = GATE.read_text(encoding="utf-8")
        for token in (
            "tests.test_training_progress_durability_concurrency",
            "tests.test_w2_training_progress_crash_recovery",
            "tests.test_training_authority_convergence",
            "tests.test_local_profile_recursion_boundary",
            "tests.test_d06_v2_gametree_resume_discard_guard",
            "python -m acs.selftest",
            "python run_accessible_chess.py --diagnostic",
        ):
            with self.subTest(token=token):
                self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
