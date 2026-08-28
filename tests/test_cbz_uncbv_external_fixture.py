from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import tempfile
import unittest

from acs.cbv_extractor import ExternalCbvExtractorConfig
from acs.cbz_extractor import (
    CbzExtractCode,
    CbzExtractError,
    extract_cbz_external,
)


UNCBV_COMMIT = "3c18e8a7c6a30c21f945a1ab5462521c306dca57"


def _external_environment_ready() -> bool:
    return all(
        os.environ.get(name)
        for name in (
            "UNCBV_BINARY",
            "UNCBV_BINARY_SHA256",
            "UNCBV_CBZ_FIXTURE",
            "UNCBV_CBZ_DECRYPTED_ORACLE",
            "UNCBV_CBZ_EXPECTED_DIR",
        )
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@unittest.skipUnless(
    _external_environment_ready(),
    "exact pinned uncbv CBZ fixture environment is not configured",
)
class CbzUncbvExternalFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Path(os.environ["UNCBV_CBZ_FIXTURE"])
        self.decrypted_oracle = Path(
            os.environ["UNCBV_CBZ_DECRYPTED_ORACLE"]
        )
        self.expected_dir = Path(os.environ["UNCBV_CBZ_EXPECTED_DIR"])
        self.config = ExternalCbvExtractorConfig(
            Path(os.environ["UNCBV_BINARY"]),
            expected_backend_sha256=os.environ["UNCBV_BINARY_SHA256"],
            timeout_seconds=300,
            max_source_bytes=64 * 1024 * 1024,
            max_extracted_bytes=256 * 1024 * 1024,
        )

    def test_exact_upstream_cbz_fixture_decrypts_stages_extracts_and_matches_oracle(self) -> None:
        self.assertEqual(self.fixture.name.lower(), "small.cbz")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.mkdir()
            result = extract_cbz_external(
                self.fixture,
                output,
                self.config,
                "password",
            )
            self.assertEqual(result.backend_name, "uncbv")
            self.assertEqual(
                result.decrypted_cbv_sha256,
                sha256(self.decrypted_oracle.read_bytes()).hexdigest(),
            )
            self.assertEqual(_files(output), _files(self.expected_dir))
            self.assertGreater(result.entry_count, 1)
            self.assertGreater(result.extracted_bytes, 0)
            self.assertTrue(result.primary_path.is_file())
            self.assertEqual(result.primary_path.suffix.lower(), ".cbh")

    def test_wrong_password_fails_closed_and_never_publishes_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.mkdir()
            with self.assertRaises(CbzExtractError) as caught:
                extract_cbz_external(
                    self.fixture,
                    output,
                    self.config,
                    "definitely-wrong",
                )
            self.assertIn(
                caught.exception.code,
                {
                    CbzExtractCode.DECRYPTED_ARCHIVE_INVALID,
                    CbzExtractCode.CBV_STAGE_FAILED,
                },
            )
            self.assertEqual(list(output.iterdir()), [])
            self.assertNotIn("definitely-wrong", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
