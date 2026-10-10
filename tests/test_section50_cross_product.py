import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from acs.ai_provider_gateway import AIProviderGateway, ProviderProfile
from acs.section50_cross_product import MoveObservation, Section50Error, probe_video, qualify_cross_product


class _Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return json.dumps(self.payload).encode("utf-8")


class Section50CrossProductTests(unittest.TestCase):
    def _video(self, root: Path, suffix: str = ".webm") -> Path:
        output = root / ("lawful-cc0-fixture" + suffix)
        codec = "libvpx-vp9" if suffix == ".webm" else "mpeg4"
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=4", "-t", "1", "-c:v", codec, "-y", str(output)],
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return output

    def test_real_webm_decode_canonical_consumers_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._video(root)
            seen = []
            def consumer(name):
                def run(fen):
                    seen.append((name, fen))
                    return {"provider": name, "model": "deterministic-test", "tokens": 7}
                return run
            receipt = qualify_cross_product(
                source, source_id="acs-owned-generated-board-fixture", license_id="CC0-1.0",
                observations=[MoveObservation("e2e4", 0.1, 0.99), MoveObservation("e7e5", 0.4, 0.98, "black")],
                settings_path=root / "settings.json",
                consumers={name: consumer(name) for name in ("stockfish", "books", "library", "agent")},
            )
            self.assertEqual(receipt["restart"]["status"], "PASS")
            self.assertEqual(receipt["canonical"]["terminal_fen"], seen[0][1])
            self.assertEqual({name for name, _fen in seen}, {"stockfish", "books", "library", "agent"})
            self.assertTrue(all(item["status"] == "PASS" for item in receipt["consumers"].values()))
            self.assertEqual(len(receipt["source"]["frames"]), 2)

    def test_mp4_probe_and_adversarial_observation_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._video(root, ".mp4")
            self.assertEqual(probe_video(source)["container"], "mp4")
            with self.assertRaisesRegex(Section50Error, "canonical legal move"):
                qualify_cross_product(
                    source, source_id="owned", license_id="CC0-1.0",
                    observations=[MoveObservation("e2e5", 0.1, 0.9)], settings_path=root / "bad.json",
                    consumers={name: (lambda _fen: {}) for name in ("stockfish", "books", "library", "agent")},
                )

    def test_mistral_first_plus_two_provider_protocols_are_normalized(self):
        payloads = []
        def opener(request, timeout):
            body = json.loads(request.data)
            payloads.append((request.full_url, body, timeout))
            if request.full_url.endswith("/api/chat"):
                return _Response({"message": {"content": "local"}, "prompt_eval_count": 3, "eval_count": 2})
            return _Response({"choices": [{"message": {"content": "remote"}}], "usage": {"total_tokens": 5}})
        profiles = {
            "mistral": ProviderProfile("mistral", "https://mistral.test/v1", "mistral-small", "TEST_MISTRAL_KEY"),
            "second": ProviderProfile("second", "https://second.test/v1", "second-model", "TEST_SECOND_KEY"),
            "local": ProviderProfile("local", "http://127.0.0.1:11434", "local-model", "", protocol="ollama-chat"),
        }
        gateway = AIProviderGateway(profiles, opener=opener, sleep=lambda _value: None)
        from unittest.mock import patch
        from acs.ai_provider_gateway import ProviderRequest
        with patch.dict("os.environ", {"TEST_MISTRAL_KEY": "secret-a", "TEST_SECOND_KEY": "secret-b"}):
            results = [gateway.complete(name, ProviderRequest(({"role": "user", "content": "position"},))) for name in ("mistral", "second", "local")]
        self.assertEqual([item.provider for item in results], ["mistral", "second", "local"])
        self.assertEqual([item.text for item in results], ["remote", "remote", "local"])
        self.assertEqual(len(payloads), 3)
        self.assertNotIn("secret-a", json.dumps(payloads))


if __name__ == "__main__":
    unittest.main()
