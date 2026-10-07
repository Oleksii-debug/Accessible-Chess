from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / ".github" / "workflows" / "media-agent-intake-convergence.yml"


class MediaAgentIntakeConvergenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = GATE.read_text(encoding="utf-8")

    def test_gate_is_exact_head_dual_os_and_fail_closed(self) -> None:
        for token in (
            "ubuntu-22.04",
            "windows-2025",
            "EXPECTED_HEAD:",
            "BASE_SHA: 0a92698bbb923ef6d7bc2d672e3fd30554fb0138",
            "INITIAL_INTAKE_HEAD: e2aa2402e19f793a7f0fa1c0876ca57a0df62178",
            "PROVIDER_HEAD: a5ea861baa33305a20bffd4226ca32af9d8825be",
            "PROVIDER_MERGE: 94fa7ae543bc8895c9abd6b69f41704693237d64",
            "PROTOCOL_HEAD: c7c497343c3e6e21e49949d904eef0c9cb1b1720",
            "PROTOCOL_MERGE: fbbfe50eaaf9b716edb9eb9f830ce48bc53ab0a8",
            'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"',
            'test "$changed" = "$expected"',
            "MEDIA_AGENT_INTAKE_GEOMETRY=PASS",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)
        self.assertNotIn("continue-on-error:", self.text)

    def test_gate_pins_provider_and_protocol_runtime_blobs(self) -> None:
        for token in (
            "e9127b209ec8c1fb50dd4f916753763084d783f1",
            "1190dd7e39a88692f3de5dfcba92c698913e711c",
            "682bd87b21a3f440e563965a0cbb07c63b29d5c8",
            "816f35f3baca039115d8d9db33adb3d9bb1d31bf",
            "11c1f5aad3a2fdbae62417d477f2d0b3a390b8cb",
            "0ab21c0b8529e8ece4b722392a2f907a65672763",
            "647d431c7e079f0e9b716d9fe80fca2289bc243b",
            "ec501c7facf9723d8696b6cf88b9680e26c7f44d",
            "1300eb8284692ef89bcda508d0aff579a45598cf",
            "b195a5d2866da4286b1ecbdaa681e960875c1612",
            "2d8aae760d3d7cda4d4f3a34139f069fdd1e4e78",
            "a065506d150df96de97bba9b2b506a5b4ab9243b",
            "5d466ecdb39b49549f2183c4c04263ca427ee1c3",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_gate_runs_composed_agent_safety_contracts(self) -> None:
        for token in (
            "tests.test_agent_model_response_authority",
            "tests.test_agent_protocol_json_safety",
            "tests.test_crossrepo_runtime_integration",
            "tests.test_crossrepo_agent_model_numeric",
            "tests.test_universal_chess_agent_crossrepo",
            "tests.test_chess_agent_tools_crossrepo",
            "tests.test_agent_checkpoint_crossrepo",
            "tests.test_agent_retry_crossrepo",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_gate_runs_media_persistence_and_process_contracts(self) -> None:
        for token in (
            "tests.test_crossrepo_media_process_files",
            "tests.test_media_audio_crossrepo",
            "tests.test_media_foundation_crossrepo",
            "tests.test_media_timeline_store",
            "tests.test_media_agent_intake_convergence_20261005",
            "tests.test_media_agent_safety_primitives_20261005",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)


if __name__ == "__main__":
    unittest.main()
