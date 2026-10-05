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
        self.assertIn("PRE_RECONVERGENCE_BASE_HEAD: 42fe13e70dc71d52cf54b930e12c05ce0fb3ff20", text)
        self.assertIn("FOCUS_WINDOWS_BASE_HEAD: d14081a181ae204f657123ae08a5aadc36256703", text)
        self.assertIn("BASE_RECONVERGENCE_MERGE: 5e9ba4711224c9e5b402f2a77e79e275bdb40fa1", text)
        self.assertIn('test "$(git show -s --format=%P "$BASE_RECONVERGENCE_MERGE")" = "$FOCUS_WINDOWS_BASE_HEAD $PRE_RECONVERGENCE_BASE_HEAD"', text)
        self.assertIn("PRE_LATEST_BASE_RECONVERGENCE: 5e9ba4711224c9e5b402f2a77e79e275bdb40fa1", text)
        self.assertIn("BASE_HEAD: 298a3d982f79caf126560a7017a7a1b65e25816a", text)
        self.assertIn("LATEST_BASE_RECONVERGENCE_MERGE: fe8d2b080deff5f1983df0cccac56aa68f053205", text)
        self.assertIn('test "$(git show -s --format=%P "$LATEST_BASE_RECONVERGENCE_MERGE")" = "$PRE_LATEST_BASE_RECONVERGENCE $BASE_HEAD"', text)
        self.assertIn('git merge-base --is-ancestor "$BASE_HEAD" HEAD', text)
        self.assertIn('test "$(git merge-base "$BASE_HEAD" HEAD)" = "$BASE_HEAD"', text)
        self.assertIn('git merge-base --is-ancestor "$SOURCE_HEAD" HEAD', text)
        self.assertNotIn('git show -s --format=%P HEAD', text)
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
