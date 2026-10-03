from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_REF = "work/full-product-teacher-education-reachability-20260911"
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "current-sound-profiles-contract.yml",
    ROOT / ".github" / "workflows" / "profiled-windows-sound-playback.yml",
    ROOT / ".github" / "workflows" / "sound-settings-application.yml",
)


class SoundProfileWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.texts = {path.name: path.read_text(encoding="utf-8") for path in WORKFLOWS}

    def test_successor_workflows_have_no_static_product_sha_pin(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertNotIn("CURRENT_PRODUCT_BASE", text)

    def test_successor_scope_never_uses_historical_pull_request_base_sha(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertNotIn("github.event.pull_request.base.sha", text)
                self.assertIn("github.event.pull_request.base.ref", text)
                self.assertIn(PRODUCT_REF, text)

    def test_live_product_branch_is_the_runtime_authority(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertIn(f"product_ref='{PRODUCT_REF}'", text)
                self.assertIn(
                    'git fetch --no-tags origin "refs/heads/$product_ref"',
                    text,
                )
                self.assertIn('live_product="$(git rev-parse FETCH_HEAD)"', text)
                self.assertIn("SOUND_PRODUCT_BASE=", text)

    def test_manual_dispatch_keeps_the_same_candidate_and_product_proof(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertIn(
                    "github.event.pull_request.head.sha || github.sha",
                    text,
                )
                self.assertIn(
                    "if [ '${{ github.event_name }}' = 'pull_request' ]; then",
                    text,
                )
                if name != "current-sound-profiles-contract.yml":
                    self.assertNotIn(
                        "if: github.event_name == 'pull_request'",
                        text,
                    )

    def test_each_candidate_proves_live_product_ancestry(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                if name == "current-sound-profiles-contract.yml":
                    self.assertIn('base="$OWNER_PRODUCT_BASE"', text)
                    self.assertIn('base="$live_product"', text)
                    self.assertIn('git cat-file -e "${base}^{commit}"', text)
                    self.assertIn(
                        'test "$(git merge-base "$base" HEAD)" = "$base"',
                        text,
                    )
                    self.assertIn('git diff --check "$base" HEAD', text)
                else:
                    self.assertIn('git cat-file -e "$live_product^{commit}"', text)
                    self.assertIn(
                        'git merge-base --is-ancestor "$live_product" HEAD',
                        text,
                    )
                    self.assertIn(
                        'test "$(git merge-base "$live_product" HEAD)" = "$live_product"',
                        text,
                    )
                    self.assertIn('git diff --check "$live_product" HEAD', text)


if __name__ == "__main__":
    unittest.main()
