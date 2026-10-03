from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_REF = "work/full-product-teacher-education-reachability-20260911"
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "current-sound-profiles-contract.yml",
    ROOT / ".github" / "workflows" / "profiled-windows-sound-playback.yml",
    ROOT / ".github" / "workflows" / "sound-settings-application.yml",
)


def _current_product_pin(text: str) -> str:
    match = re.search(r"(?m)^\s*CURRENT_PRODUCT_BASE:\s*([0-9a-f]{40})\s*$", text)
    if match is None:
        raise AssertionError("workflow must declare one exact CURRENT_PRODUCT_BASE")
    return match.group(1)


class SoundProfileWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.texts = {path.name: path.read_text(encoding="utf-8") for path in WORKFLOWS}

    def test_all_successor_workflows_share_one_pinned_product_authority(self) -> None:
        pins = {_current_product_pin(text) for text in self.texts.values()}
        self.assertEqual(1, len(pins))

    def test_successor_scope_never_uses_historical_pull_request_base_sha(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertNotIn("github.event.pull_request.base.sha", text)
                self.assertIn(
                    "github.event.pull_request.base.ref",
                    text,
                )
                self.assertIn(PRODUCT_REF, text)

    def test_pinned_product_must_equal_fresh_live_base_branch(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertIn(
                    'git fetch --no-tags origin "refs/heads/${{ github.event.pull_request.base.ref }}"',
                    text,
                )
                self.assertIn('live_product="$(git rev-parse FETCH_HEAD)"', text)
                self.assertIn(
                    'test "$live_product" = "$CURRENT_PRODUCT_BASE"',
                    text,
                )

    def test_each_candidate_proves_its_pinned_product_ancestry(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                if name == "current-sound-profiles-contract.yml":
                    self.assertIn('base="$OWNER_PRODUCT_BASE"', text)
                    self.assertIn('base="$CURRENT_PRODUCT_BASE"', text)
                    self.assertIn('git cat-file -e "${base}^{commit}"', text)
                    self.assertIn(
                        'test "$(git merge-base "$base" HEAD)" = "$base"',
                        text,
                    )
                    self.assertIn('git diff --check "$base" HEAD', text)
                else:
                    self.assertIn('git cat-file -e "$CURRENT_PRODUCT_BASE^{commit}"', text)
                    self.assertIn(
                        'git merge-base --is-ancestor "$CURRENT_PRODUCT_BASE" HEAD',
                        text,
                    )
                    self.assertIn(
                        'test "$(git merge-base "$CURRENT_PRODUCT_BASE" HEAD)" = "$CURRENT_PRODUCT_BASE"',
                        text,
                    )
                    self.assertIn('git diff --check "$CURRENT_PRODUCT_BASE" HEAD', text)


if __name__ == "__main__":
    unittest.main()
