from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from acs.cbone_acceptance import (
    CBONE_ACCEPTANCE_PROTOCOL,
    CboneAcceptanceCode,
    CboneAcceptanceError,
    CboneAcceptanceManifest,
    qualify_cbone_candidate,
)
from acs.chessbase_adapter import probe_chessbase_source
from acs.gametree import parse_games


PGN_E4 = """[Event \"CBONE acceptance oracle\"]
[Site \"Test\"]
[Date \"2026.08.31\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 e5 2. Nf3 Nc6 *
"""

PGN_D4 = """[Event \"CBONE acceptance oracle\"]
[Site \"Test\"]
[Date \"2026.08.31\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. d4 d5 2. Nf3 Nf6 *
"""


class V2CboneSemanticAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "real-shape-test.cbone"
        self.source_bytes = b"synthetic fixture bytes; never a CBONE format claim\n"
        self.source.write_bytes(self.source_bytes)

    def _manifest(
        self,
        *,
        oracle_pgn: str = PGN_E4,
        source_sha256: str | None = None,
        automated_use: bool = True,
        expected_game_count: int = 1,
    ) -> CboneAcceptanceManifest:
        return CboneAcceptanceManifest(
            backend_name="qualified-reader-placeholder",
            backend_commit="1" * 40,
            backend_license_spdx="GPL-3.0-only",
            backend_license_reference="https://example.invalid/reader-license",
            source_sha256=source_sha256 or sha256(self.source_bytes).hexdigest(),
            source_rights_reference="https://example.invalid/source-rights",
            source_automated_use_permitted=automated_use,
            oracle_pgn_sha256=sha256(oracle_pgn.encode("utf-8")).hexdigest(),
            oracle_provenance_reference="https://example.invalid/oracle-provenance",
            expected_game_count=expected_game_count,
        )

    @staticmethod
    def _candidate_from(pgn: str):
        def candidate(_source: Path):
            return tuple(parse_games(pgn))

        return candidate

    def test_synthetic_acceptance_pass_cannot_promote_runtime_support(self) -> None:
        report = qualify_cbone_candidate(
            self.source,
            self._manifest(),
            self._candidate_from(PGN_E4),
            oracle_pgn=PGN_E4,
        )

        self.assertEqual(report.game_count, 1)
        self.assertEqual(report.record_digests, report.roundtrip_record_digests)
        self.assertEqual(report.backend_commit, "1" * 40)
        self.assertEqual(report.backend_license_spdx, "GPL-3.0-only")

        # The acceptance harness is evidence tooling only.  Filename/topology
        # recognition remains fail-closed until a real reader/corpus/oracle and
        # the downstream Product gates are independently accepted.
        probe = probe_chessbase_source(self.source)
        self.assertTrue(probe.recognized)
        self.assertEqual(probe.source_kind, "single_file_database")
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)
        self.assertFalse(hasattr(report, "safe_to_import"))
        self.assertFalse(hasattr(report, "supported"))

    def test_manifest_requires_explicit_automated_use_permission(self) -> None:
        with self.assertRaises(ValueError):
            self._manifest(automated_use=False)

    def test_manifest_requires_exact_protocol_and_pinned_commit(self) -> None:
        values = dict(
            backend_name="reader",
            backend_commit="1" * 40,
            backend_license_spdx="MIT",
            backend_license_reference="https://example.invalid/license",
            source_sha256=sha256(self.source_bytes).hexdigest(),
            source_rights_reference="https://example.invalid/rights",
            source_automated_use_permitted=True,
            oracle_pgn_sha256=sha256(PGN_E4.encode("utf-8")).hexdigest(),
            oracle_provenance_reference="https://example.invalid/oracle",
            expected_game_count=1,
        )
        with self.assertRaises(ValueError):
            CboneAcceptanceManifest(**values, protocol_id="cbone-guessed-v0")
        values["backend_commit"] = "ABC"
        with self.assertRaises(ValueError):
            CboneAcceptanceManifest(**values, protocol_id=CBONE_ACCEPTANCE_PROTOCOL)

    def test_wrong_extension_or_source_hash_fails_before_decoder(self) -> None:
        wrong_extension = self.source.with_suffix(".cbh")
        wrong_extension.write_bytes(self.source_bytes)
        calls: list[Path] = []

        def candidate(path: Path):
            calls.append(path)
            return tuple(parse_games(PGN_E4))

        with self.assertRaises(CboneAcceptanceError) as caught:
            qualify_cbone_candidate(
                wrong_extension,
                self._manifest(),
                candidate,
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CboneAcceptanceCode.WRONG_SOURCE)
        self.assertEqual(calls, [])

        with self.assertRaises(CboneAcceptanceError) as caught:
            qualify_cbone_candidate(
                self.source,
                self._manifest(source_sha256="0" * 64),
                candidate,
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CboneAcceptanceCode.WRONG_SOURCE)
        self.assertEqual(calls, [])

    def test_source_mutation_invalidates_all_candidate_output(self) -> None:
        def mutating_candidate(source: Path):
            source.write_bytes(b"mutated by untrusted candidate")
            return tuple(parse_games(PGN_E4))

        with self.assertRaises(CboneAcceptanceError) as caught:
            qualify_cbone_candidate(
                self.source,
                self._manifest(),
                mutating_candidate,
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CboneAcceptanceCode.SOURCE_CHANGED)

    def test_candidate_exception_is_bounded_and_source_remains_authoritative(self) -> None:
        original = self.source.read_bytes()

        def failing_candidate(_source: Path):
            raise RuntimeError("reader internals that must not escape")

        with self.assertRaises(CboneAcceptanceError) as caught:
            qualify_cbone_candidate(
                self.source,
                self._manifest(),
                failing_candidate,
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CboneAcceptanceCode.BACKEND_FAILED)
        self.assertNotIn("reader internals", str(caught.exception))
        self.assertEqual(self.source.read_bytes(), original)

    def test_candidate_must_return_canonical_pgn_games(self) -> None:
        with self.assertRaises(CboneAcceptanceError) as caught:
            qualify_cbone_candidate(
                self.source,
                self._manifest(),
                lambda _source: [object()],
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(
            caught.exception.code,
            CboneAcceptanceCode.INVALID_DECODED_DATABASE,
        )

    def test_every_decoded_game_is_replayed_by_canonical_legality(self) -> None:
        games = parse_games(PGN_E4)
        games[0].line.moves[0].san = "e5"  # illegal for White from the start position

        with self.assertRaises(CboneAcceptanceError) as caught:
            qualify_cbone_candidate(
                self.source,
                self._manifest(),
                lambda _source: tuple(games),
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CboneAcceptanceCode.ILLEGAL_GAME)

    def test_independent_oracle_hash_is_required(self) -> None:
        manifest = self._manifest(oracle_pgn=PGN_D4)
        with self.assertRaises(CboneAcceptanceError) as caught:
            qualify_cbone_candidate(
                self.source,
                manifest,
                self._candidate_from(PGN_E4),
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CboneAcceptanceCode.INVALID_ORACLE)

    def test_semantic_difference_from_independent_oracle_fails(self) -> None:
        manifest = self._manifest(oracle_pgn=PGN_D4)
        with self.assertRaises(CboneAcceptanceError) as caught:
            qualify_cbone_candidate(
                self.source,
                manifest,
                self._candidate_from(PGN_E4),
                oracle_pgn=PGN_D4,
            )
        self.assertEqual(caught.exception.code, CboneAcceptanceCode.ORACLE_MISMATCH)

    def test_expected_game_count_is_exact(self) -> None:
        with self.assertRaises(CboneAcceptanceError) as caught:
            qualify_cbone_candidate(
                self.source,
                self._manifest(expected_game_count=2),
                self._candidate_from(PGN_E4),
                oracle_pgn=PGN_E4,
            )
        self.assertEqual(caught.exception.code, CboneAcceptanceCode.ORACLE_MISMATCH)


if __name__ == "__main__":
    unittest.main()
