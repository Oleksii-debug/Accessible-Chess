from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from acs.cbcloud_acceptance import (
    CBCLOUD_ACCEPTANCE_PROTOCOL,
    CbcloudAcceptanceCode,
    CbcloudAcceptanceError,
    CbcloudAcceptanceManifest,
    CbcloudFamilyMemberEvidence,
    qualify_cbcloud_candidate,
)
from acs.chessbase_adapter import probe_chessbase_source
from acs.gametree import parse_games


PGN_E4 = """[Event \"CBCLOUD acceptance oracle\"]
[Site \"Test\"]
[Date \"2026.08.31\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 e5 2. Nf3 Nc6 *
"""

PGN_D4 = """[Event \"CBCLOUD acceptance oracle\"]
[Site \"Test\"]
[Date \"2026.08.31\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. d4 d5 2. Nf3 Nf6 *
"""


class V2CbcloudSemanticAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # Synthetic names deliberately do not claim real CBCLOUD companion suffixes.
        self.names = (
            "sample.cbcloud",
            "sample.synthetic-a",
            "sample.synthetic-b",
            "sample.synthetic-c",
        )
        self.bytes_by_name = {
            name: f"synthetic bytes for {index}; never a CBCLOUD format claim\n".encode()
            for index, name in enumerate(self.names)
        }
        for name, payload in self.bytes_by_name.items():
            (self.root / name).write_bytes(payload)
        self.primary = self.root / self.names[0]

    def _members(self) -> tuple[CbcloudFamilyMemberEvidence, ...]:
        return tuple(
            CbcloudFamilyMemberEvidence(
                filename=name,
                sha256=sha256(self.bytes_by_name[name]).hexdigest(),
            )
            for name in self.names
        )

    def _manifest(
        self,
        *,
        oracle_pgn: str = PGN_E4,
        members: tuple[CbcloudFamilyMemberEvidence, ...] | None = None,
        automated_use: bool = True,
        expected_game_count: int = 1,
    ) -> CbcloudAcceptanceManifest:
        return CbcloudAcceptanceManifest(
            backend_name="qualified-reader-placeholder",
            backend_commit="1" * 40,
            backend_license_spdx="GPL-3.0-only",
            backend_license_reference="https://example.invalid/reader-license",
            family_members=members or self._members(),
            family_rights_reference="https://example.invalid/family-rights",
            family_automated_use_permitted=automated_use,
            oracle_pgn_sha256=sha256(oracle_pgn.encode("utf-8")).hexdigest(),
            oracle_provenance_reference="https://example.invalid/oracle-provenance",
            expected_game_count=expected_game_count,
        )

    @staticmethod
    def _candidate_from(pgn: str):
        def candidate(_family: tuple[Path, ...]):
            return tuple(parse_games(pgn))

        return candidate

    def test_synthetic_pass_cannot_promote_runtime_support(self) -> None:
        seen: list[tuple[str, ...]] = []

        def candidate(family: tuple[Path, ...]):
            seen.append(tuple(path.name for path in family))
            return tuple(parse_games(PGN_E4))

        report = qualify_cbcloud_candidate(
            self.primary,
            self._manifest(),
            candidate,
            oracle_pgn=PGN_E4,
        )

        self.assertEqual(seen, [self.names])
        self.assertEqual(len(report.family), 4)
        self.assertEqual(report.game_count, 1)
        self.assertEqual(report.record_digests, report.roundtrip_record_digests)
        self.assertFalse(hasattr(report, "safe_to_import"))
        self.assertFalse(hasattr(report, "supported"))

        # The harness is not runtime registration. #404 intentionally leaves
        # CBCLOUD outside the Product filename adapter until topology is qualified.
        probe = probe_chessbase_source(self.primary)
        self.assertFalse(probe.recognized)
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)

    def test_manifest_requires_exact_four_files_and_one_primary(self) -> None:
        with self.assertRaises(ValueError):
            self._manifest(members=self._members()[:3])

        no_primary = tuple(
            CbcloudFamilyMemberEvidence(f"member-{index}.synthetic", "0" * 64)
            for index in range(4)
        )
        with self.assertRaises(ValueError):
            self._manifest(members=no_primary)

        two_primary = list(self._members())
        two_primary[-1] = CbcloudFamilyMemberEvidence("other.cbcloud", "0" * 64)
        with self.assertRaises(ValueError):
            self._manifest(members=tuple(two_primary))

    def test_manifest_rejects_case_collisions_and_cross_platform_path_names(self) -> None:
        members = list(self._members())
        members[-1] = CbcloudFamilyMemberEvidence("SAMPLE.SYNTHETIC-A", "0" * 64)
        with self.assertRaises(ValueError):
            self._manifest(members=tuple(members))

        for bad in ("../outside.bin", "..\\outside.bin", "dir/file.bin", "dir\\file.bin"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                CbcloudFamilyMemberEvidence(bad, "0" * 64)

    def test_manifest_requires_explicit_rights_and_pinned_backend(self) -> None:
        with self.assertRaises(ValueError):
            self._manifest(automated_use=False)

        values = dict(
            backend_name="reader",
            backend_commit="1" * 40,
            backend_license_spdx="MIT",
            backend_license_reference="https://example.invalid/license",
            family_members=self._members(),
            family_rights_reference="https://example.invalid/rights",
            family_automated_use_permitted=True,
            oracle_pgn_sha256=sha256(PGN_E4.encode("utf-8")).hexdigest(),
            oracle_provenance_reference="https://example.invalid/oracle",
            expected_game_count=1,
        )
        with self.assertRaises(ValueError):
            CbcloudAcceptanceManifest(**values, protocol_id="cbcloud-guessed-v0")
        values["backend_commit"] = "ABC"
        with self.assertRaises(ValueError):
            CbcloudAcceptanceManifest(**values, protocol_id=CBCLOUD_ACCEPTANCE_PROTOCOL)

    def test_wrong_primary_or_member_hash_fails_before_reader(self) -> None:
        calls: list[tuple[Path, ...]] = []

        def candidate(family: tuple[Path, ...]):
            calls.append(family)
            return tuple(parse_games(PGN_E4))

        wrong_primary = self.root / "wrong.cbcloud"
        wrong_primary.write_bytes(self.bytes_by_name[self.names[0]])
        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(wrong_primary, self._manifest(), candidate, oracle_pgn=PGN_E4)
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.WRONG_SOURCE)
        self.assertEqual(calls, [])

        members = list(self._members())
        members[2] = CbcloudFamilyMemberEvidence(members[2].filename, "0" * 64)
        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(
                self.primary,
                self._manifest(members=tuple(members)),
                candidate,
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.WRONG_SOURCE)
        self.assertEqual(calls, [])

    def test_missing_companion_fails_before_reader(self) -> None:
        (self.root / self.names[-1]).unlink()
        calls: list[tuple[Path, ...]] = []
        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(
                self.primary,
                self._manifest(),
                lambda family: calls.append(family) or tuple(parse_games(PGN_E4)),
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.WRONG_SOURCE)
        self.assertEqual(calls, [])

    def test_mutating_any_family_member_invalidates_all_output(self) -> None:
        def mutating_candidate(family: tuple[Path, ...]):
            family[2].write_bytes(b"mutated by untrusted reader")
            return tuple(parse_games(PGN_E4))

        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(
                self.primary,
                self._manifest(),
                mutating_candidate,
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.SOURCE_CHANGED)

    def test_deleting_family_member_invalidates_all_output(self) -> None:
        def deleting_candidate(family: tuple[Path, ...]):
            family[-1].unlink()
            return tuple(parse_games(PGN_E4))

        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(
                self.primary,
                self._manifest(),
                deleting_candidate,
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.SOURCE_CHANGED)

    def test_reader_exception_is_sanitized_and_family_remains_authoritative(self) -> None:
        original = {name: (self.root / name).read_bytes() for name in self.names}

        def failing_candidate(_family: tuple[Path, ...]):
            raise RuntimeError("private backend path and decoder internals")

        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(
                self.primary,
                self._manifest(),
                failing_candidate,
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.BACKEND_FAILED)
        self.assertNotIn("decoder internals", str(caught.exception))
        self.assertEqual(original, {name: (self.root / name).read_bytes() for name in self.names})

    def test_reader_must_return_canonical_games(self) -> None:
        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(
                self.primary,
                self._manifest(),
                lambda _family: [object()],
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.INVALID_DECODED_DATABASE)

    def test_every_decoded_game_uses_canonical_legality(self) -> None:
        games = parse_games(PGN_E4)
        games[0].line.moves[0].san = "e5"
        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(
                self.primary,
                self._manifest(),
                lambda _family: tuple(games),
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.ILLEGAL_GAME)

    def test_oracle_hash_and_semantic_identity_are_independent_gates(self) -> None:
        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(
                self.primary,
                self._manifest(oracle_pgn=PGN_D4),
                self._candidate_from(PGN_E4),
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.INVALID_ORACLE)

        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(
                self.primary,
                self._manifest(oracle_pgn=PGN_D4),
                self._candidate_from(PGN_E4),
                oracle_pgn=PGN_D4,
            )
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.ORACLE_MISMATCH)

    def test_expected_game_count_is_exact(self) -> None:
        with self.assertRaises(CbcloudAcceptanceError) as caught:
            qualify_cbcloud_candidate(
                self.primary,
                self._manifest(expected_game_count=2),
                self._candidate_from(PGN_E4),
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CbcloudAcceptanceCode.ORACLE_MISMATCH)


if __name__ == "__main__":
    unittest.main()
