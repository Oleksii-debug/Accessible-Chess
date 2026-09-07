from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_package_assembler import (
    Version2PackageAssemblyError,
    assemble_version2_package_tree,
)


_SHA = "a" * 40


class Version2PackagePayloadCompletenessEvidenceTests(unittest.TestCase):
    def test_prepared_product_without_release_critical_payload_is_rejected(self) -> None:
        """A package gate must not certify an EXE-only skeleton as release-complete.

        The Windows/NVDA release contract requires the prepared product payload to
        contain the bundled official Stockfish runtime and the real nine-event
        sound pack.  The package also needs the corresponding Stockfish GPL source
        and notice payload.  Assembly/preflight may be separate from acquisition,
        but it must fail closed when those release-critical ingredients are absent.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product = root / "prepared-product"
            notices = root / "notices"
            output = root / "candidate"
            (product / "web").mkdir(parents=True)
            (product / "AccessibleChess.exe").write_bytes(b"MZ\0incomplete-v2")
            (product / "web" / "index.html").write_text(
                "<main>Accessible Chess</main>\n", encoding="utf-8"
            )
            notices.mkdir()
            (notices / "NOTICE.txt").write_text(
                "Generic notice only; Stockfish corresponding source is absent.\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                Version2PackageAssemblyError,
                "(?:payload|Stockfish|sound|release-critical|required)",
            ):
                assemble_version2_package_tree(
                    product,
                    notices,
                    output,
                    integration_sha=_SHA,
                )

            self.assertFalse(
                output.exists(),
                "an incomplete prepared product must never become a validated package",
            )


if __name__ == "__main__":
    unittest.main()
