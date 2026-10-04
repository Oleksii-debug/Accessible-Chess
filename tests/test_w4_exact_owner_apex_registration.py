from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "w4-v2-p0-fresh-windows-candidate.yml"


class W4ExactOwnerApexRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_registered_w4_targets_fixed_owner_release_apex(self) -> None:
        self.assertIn(
            "FULL_PRODUCT_BRANCH: work/full-product-teacher-education-reachability-20260911",
            self.text,
        )
        self.assertIn(
            "RELEASE_APEX_BRANCH: qualification/owner-portable-candidate-20261004-sol6f2",
            self.text,
        )
        self.assertNotIn("release_apex_branch:", self.text)
        self.assertEqual(
            self.text.count('git fetch --no-tags origin "$RELEASE_APEX_BRANCH"'),
            2,
        )
        self.assertEqual(
            self.text.count('release_live="$(git rev-parse "origin/$RELEASE_APEX_BRANCH")"'),
            2,
        )

    def test_owner_apex_must_descend_from_live_full_product(self) -> None:
        proof = 'git merge-base --is-ancestor "$full_product_live" "$release_live"'
        self.assertEqual(self.text.count(proof), 2)
        self.assertIn(
            "Live owner release apex %s does not contain live Full Product head %s",
            self.text,
        )
        self.assertIn("STALE_W4_RELEASE_APEX_ANCESTRY", self.text)

    def test_requested_sha_and_preupload_freshness_bind_to_release_apex(self) -> None:
        bind = self.text.index('live="$release_live"')
        requested = self.text.index('test "$requested" = "$live"')
        materialize = self.text.index("Materialize exact integrated Product worktree")
        self.assertLess(bind, requested)
        self.assertLess(requested, materialize)
        self.assertIn("Requested SHA %s is not live owner release apex head %s", self.text)
        self.assertIn("W4_WORKFLOW_RELEASE_APEX_IDENTITY=PASS", self.text)

        freshness_step = self.text.index(
            "Recheck workflow, Full Product ancestry and release apex freshness before artifact publication"
        )
        stale_check = self.text.index('test "$PRODUCT_SHA" = "$live"', freshness_step)
        marker = self.text.index("W4_PRE_UPLOAD_RELEASE_APEX_FRESHNESS=PASS", freshness_step)
        metadata = self.text.index("Write run-bound candidate metadata after freshness proof")
        self.assertLess(freshness_step, stale_check)
        self.assertLess(stale_check, marker)
        self.assertLess(marker, metadata)

    def test_machine_evidence_claim_boundary_is_unchanged(self) -> None:
        self.assertIn("HUMAN_TESTED=NO", self.text)
        self.assertIn("NVDA_VERIFIED=NO", self.text)
        self.assertNotIn("FINAL_WINDOWS_ZIP=YES", self.text)
        self.assertIn("VERSION2_WINDOWS_ZIP=YES", self.text)


if __name__ == "__main__":
    unittest.main()
