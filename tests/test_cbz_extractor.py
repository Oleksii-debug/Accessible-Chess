from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from acs.cbv_extractor import (
    CbvExtractCode,
    CbvExtractError,
    CbvExtraction,
    ExternalCbvExtractorConfig,
)
from acs.cbz_extractor import (
    CbzExtractCode,
    CbzExtractError,
    _run_uncbv_decrypt,
    extract_cbz_external,
)
from acs.import_contract import fingerprint


class CbzExternalExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "Archive.cbz"
        self.source.write_bytes(b"immutable encrypted archive")
        self.backend = self.root / "uncbv"
        self.backend.write_bytes(b"pinned external backend")
        self.backend_sha256 = sha256(self.backend.read_bytes()).hexdigest()
        self.config = ExternalCbvExtractorConfig(
            self.backend,
            expected_backend_sha256=self.backend_sha256,
            timeout_seconds=3,
        )
        self.output = self.root / "output"
        self.output.mkdir()

    @staticmethod
    def _write_valid_decrypted(destination: Path) -> None:
        destination.write_bytes(b"\x08\x00decrypted-cbv")

    def _successful_decrypt(
        self,
        _exe,
        _source,
        destination,
        _config,
        password,
        **_kwargs,
    ):
        self.assertEqual(password, "secret")
        self._write_valid_decrypted(Path(destination))

    def _successful_cbv_extract(self, decrypted, staged, _config):
        self.assertTrue(Path(decrypted).is_file())
        staged = Path(staged)
        (staged / "db.cbh").write_bytes(b"header")
        (staged / "db.cbg").write_bytes(b"moves")
        return CbvExtraction(
            source=fingerprint(decrypted),
            primary_path=staged / "db.cbh",
            entry_count=2,
            extracted_bytes=11,
            backend_name="uncbv",
            backend_sha256=self.backend_sha256,
        )

    def test_success_stages_then_atomically_publishes_and_cleans_decrypted_material(self) -> None:
        with mock.patch(
            "acs.cbz_extractor._run_uncbv_decrypt",
            side_effect=self._successful_decrypt,
        ), mock.patch(
            "acs.cbz_extractor.extract_cbv_external",
            side_effect=self._successful_cbv_extract,
        ):
            result = extract_cbz_external(
                self.source,
                self.output,
                self.config,
                "secret",
            )

        self.assertEqual(
            result.source.sha256,
            sha256(self.source.read_bytes()).hexdigest(),
        )
        self.assertEqual(result.primary_path, self.output / "db.cbh")
        self.assertEqual(
            result.decrypted_cbv_sha256,
            sha256(b"\x08\x00decrypted-cbv").hexdigest(),
        )
        self.assertEqual((self.output / "db.cbh").read_bytes(), b"header")
        self.assertEqual((self.output / "db.cbg").read_bytes(), b"moves")
        self.assertEqual(list(self.root.glob(".accessible-chess-cbz-*")), [])

    def test_password_validation_rejects_empty_controls_and_oversize_before_backend(self) -> None:
        passwords = (
            "",
            "line\nbreak",
            "line\rbreak",
            "nul\x00byte",
            "x" * 1025,
        )
        for password in passwords:
            with self.subTest(password_len=len(password)):
                with mock.patch("acs.cbz_extractor.subprocess.Popen") as popen:
                    with self.assertRaises(CbzExtractError) as caught:
                        extract_cbz_external(
                            self.source,
                            self.output,
                            self.config,
                            password,
                        )
                self.assertEqual(
                    caught.exception.code,
                    CbzExtractCode.PASSWORD_INVALID,
                )
                popen.assert_not_called()

    def test_non_cbz_and_2cbz_fail_closed_without_backend_execution(self) -> None:
        for suffix in (".cbv", ".2cbz"):
            candidate = self.root / ("other" + suffix)
            candidate.write_bytes(b"opaque")
            with mock.patch("acs.cbz_extractor._run_uncbv_decrypt") as decrypt:
                with self.assertRaises(CbzExtractError) as caught:
                    extract_cbz_external(
                        candidate,
                        self.output,
                        self.config,
                        "secret",
                    )
            self.assertEqual(
                caught.exception.code,
                CbzExtractCode.UNSUPPORTED_SOURCE,
            )
            decrypt.assert_not_called()

    def test_wrong_password_or_invalid_decrypted_header_never_mutates_final_output(self) -> None:
        def invalid(_exe, _source, destination, _config, _password, **_kwargs):
            Path(destination).write_bytes(b"wrong-password-garbage")

        with mock.patch(
            "acs.cbz_extractor._run_uncbv_decrypt",
            side_effect=invalid,
        ):
            with self.assertRaises(CbzExtractError) as caught:
                extract_cbz_external(
                    self.source,
                    self.output,
                    self.config,
                    "not-the-password",
                )
        self.assertEqual(
            caught.exception.code,
            CbzExtractCode.DECRYPTED_ARCHIVE_INVALID,
        )
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertNotIn("not-the-password", str(caught.exception))
        self.assertEqual(list(self.root.glob(".accessible-chess-cbz-*")), [])

    def test_cbv_stage_failure_is_atomic_and_private_temp_is_removed(self) -> None:
        with mock.patch(
            "acs.cbz_extractor._run_uncbv_decrypt",
            side_effect=self._successful_decrypt,
        ), mock.patch(
            "acs.cbz_extractor.extract_cbv_external",
            side_effect=CbvExtractError(
                "fixture failure",
                code=CbvExtractCode.OUTPUT_INVALID,
            ),
        ):
            with self.assertRaises(CbzExtractError) as caught:
                extract_cbz_external(
                    self.source,
                    self.output,
                    self.config,
                    "secret",
                )
        self.assertEqual(caught.exception.code, CbzExtractCode.CBV_STAGE_FAILED)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(self.root.glob(".accessible-chess-cbz-*")), [])

    def test_source_or_backend_mutation_after_decrypt_fails_before_cbv_stage(self) -> None:
        def mutate_source(*args, **kwargs):
            self._successful_decrypt(*args, **kwargs)
            self.source.write_bytes(b"changed encrypted archive")

        with mock.patch(
            "acs.cbz_extractor._run_uncbv_decrypt",
            side_effect=mutate_source,
        ), mock.patch("acs.cbz_extractor.extract_cbv_external") as cbv:
            with self.assertRaises(CbzExtractError) as caught:
                extract_cbz_external(
                    self.source,
                    self.output,
                    self.config,
                    "secret",
                )
        self.assertEqual(caught.exception.code, CbzExtractCode.SOURCE_CHANGED)
        cbv.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

        self.source.write_bytes(b"immutable encrypted archive")

        def mutate_backend(*args, **kwargs):
            self._successful_decrypt(*args, **kwargs)
            self.backend.write_bytes(b"changed backend")

        with mock.patch(
            "acs.cbz_extractor._run_uncbv_decrypt",
            side_effect=mutate_backend,
        ), mock.patch("acs.cbz_extractor.extract_cbv_external") as cbv:
            with self.assertRaises(CbzExtractError) as caught:
                extract_cbz_external(
                    self.source,
                    self.output,
                    self.config,
                    "secret",
                )
        self.assertEqual(caught.exception.code, CbzExtractCode.BACKEND_INVALID)
        cbv.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_cancellation_after_decrypt_discards_private_state_and_leaves_output_empty(self) -> None:
        cancelled = threading.Event()

        def decrypt(*args, **kwargs):
            self._successful_decrypt(*args, **kwargs)
            cancelled.set()

        with mock.patch(
            "acs.cbz_extractor._run_uncbv_decrypt",
            side_effect=decrypt,
        ), mock.patch("acs.cbz_extractor.extract_cbv_external") as cbv:
            with self.assertRaises(CbzExtractError) as caught:
                extract_cbz_external(
                    self.source,
                    self.output,
                    self.config,
                    "secret",
                    cancel_event=cancelled,
                )
        self.assertEqual(caught.exception.code, CbzExtractCode.CANCELLED)
        cbv.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(self.root.glob(".accessible-chess-cbz-*")), [])

    def test_publish_race_does_not_overwrite_new_final_output_content(self) -> None:
        def cbv_extract(*args, **kwargs):
            result = self._successful_cbv_extract(*args, **kwargs)
            (self.output / "arrived-during-import.txt").write_text(
                "keep",
                encoding="utf-8",
            )
            return result

        with mock.patch(
            "acs.cbz_extractor._run_uncbv_decrypt",
            side_effect=self._successful_decrypt,
        ), mock.patch(
            "acs.cbz_extractor.extract_cbv_external",
            side_effect=cbv_extract,
        ):
            with self.assertRaises(CbzExtractError) as caught:
                extract_cbz_external(
                    self.source,
                    self.output,
                    self.config,
                    "secret",
                )
        self.assertEqual(caught.exception.code, CbzExtractCode.OUTPUT_INVALID)
        self.assertEqual(
            (self.output / "arrived-during-import.txt").read_text(encoding="utf-8"),
            "keep",
        )
        self.assertFalse((self.output / "db.cbh").exists())
        self.assertEqual(list(self.root.glob(".accessible-chess-cbz-*")), [])

    def test_password_is_not_part_of_reported_error_text(self) -> None:
        with mock.patch(
            "acs.cbz_extractor._run_uncbv_decrypt",
            side_effect=CbzExtractError(
                "CBZ backend failed while decrypting the archive",
                code=CbzExtractCode.BACKEND_FAILED,
            ),
        ):
            with self.assertRaises(CbzExtractError) as caught:
                extract_cbz_external(
                    self.source,
                    self.output,
                    self.config,
                    "super-private-password",
                )
        self.assertNotIn("super-private-password", str(caught.exception))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_subprocess_boundary_puts_password_only_on_stdin(self) -> None:
        class EmptyReader:
            def read(self, _size=-1):
                return b""

            def close(self):
                return None

        class SecretSink:
            def __init__(self):
                self.written = b""

            def write(self, data):
                self.written += bytes(data)
                return len(data)

            def flush(self):
                return None

            def close(self):
                return None

        class Process:
            def __init__(self):
                self.stdin = SecretSink()
                self.stdout = EmptyReader()
                self.stderr = EmptyReader()
                self.returncode = 0

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        process = Process()
        decrypted = self.root / "private.cbv"
        with mock.patch(
            "acs.cbz_extractor.subprocess.Popen",
            return_value=process,
        ) as popen:
            _run_uncbv_decrypt(
                self.backend,
                self.source,
                decrypted,
                self.config,
                "super-secret",
                cwd=self.root,
            )

        argv = popen.call_args.args[0]
        kwargs = popen.call_args.kwargs
        self.assertEqual(argv[1], "decrypt")
        self.assertNotIn("super-secret", " ".join(map(str, argv)))
        self.assertNotIn(
            "super-secret",
            " ".join(map(str, kwargs["env"].values())),
        )
        self.assertIs(kwargs["stdin"], subprocess.PIPE)
        self.assertEqual(process.stdin.written, b"super-secret\n")

    def test_subprocess_cancellation_kills_backend_without_secret_in_error(self) -> None:
        cancelled = threading.Event()

        class EmptyReader:
            def read(self, _size=-1):
                return b""

            def close(self):
                return None

        class SecretSink:
            def write(self, data):
                self.data = bytes(data)
                return len(data)

            def flush(self):
                cancelled.set()

            def close(self):
                return None

        class Process:
            def __init__(self):
                self.stdin = SecretSink()
                self.stdout = EmptyReader()
                self.stderr = EmptyReader()
                self.returncode = None
                self.killed = False

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                if self.returncode is None:
                    raise subprocess.TimeoutExpired("uncbv", timeout or 0)
                return self.returncode

            def kill(self):
                self.killed = True
                self.returncode = -9

        process = Process()
        with mock.patch(
            "acs.cbz_extractor.subprocess.Popen",
            return_value=process,
        ):
            with self.assertRaises(CbzExtractError) as caught:
                _run_uncbv_decrypt(
                    self.backend,
                    self.source,
                    self.root / "private.cbv",
                    self.config,
                    "cancel-secret",
                    cwd=self.root,
                    cancel_event=cancelled,
                )
        self.assertTrue(process.killed)
        self.assertEqual(caught.exception.code, CbzExtractCode.CANCELLED)
        self.assertNotIn("cancel-secret", str(caught.exception))

    def test_machine_readable_contract_keeps_format_blocked_after_mechanical_path(self) -> None:
        manifest = (
            Path(__file__).parents[1]
            / "docs"
            / "automation"
            / "V2_CBZ_SECURE_EXECUTION.json"
        )
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["scope"],
            "cbz-secure-execution-mechanics-only",
        )
        self.assertEqual(payload["format_status"], "BLOCKED")
        self.assertEqual(payload["two_cbz_status"], "BLOCKED")
        self.assertEqual(
            payload["upstream_uncbv"]["commit"],
            "3c18e8a7c6a30c21f945a1ab5462521c306dca57",
        )
        self.assertTrue(payload["mechanical_contract"]["password_stdin_only"])
        self.assertTrue(
            payload["mechanical_contract"]["staged_publish_atomicity"]
        )
        self.assertFalse(
            payload["acceptance"]["independent_real_semantic_oracle"]
        )
        self.assertFalse(payload["acceptance"]["support_promotion_allowed"])
        rendered = json.dumps(payload, sort_keys=True).casefold()
        self.assertNotIn('"format_status": "supported"', rendered)
        self.assertNotIn('"format_status": "partial"', rendered)


if __name__ == "__main__":
    unittest.main()
