from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import unittest
from unittest.mock import patch

from acs.cbf_cbi_external import CbfCbiReadResult, ExternalCbfCbiReaderConfig
from acs.cbf_cbi_qualification import (
    CbfCbiOracleCode,
    CbfCbiOracleQualificationError,
    qualify_cbf_cbi_against_pgn_oracle,
)
from acs.game_identity import IDENTITY_SCHEMA_VERSION
from acs.gametree import parse_games


_GAME_A = '''[Event "Oracle A"]
[Site "Test"]
[Date "2026.09.07"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 {keep comment} e5 (1... c5 {keep variation}) 2. Nf3 Nc6 1-0
'''

_GAME_A_REORDERED = '''[Black "Beta"]
[White "Alpha"]
[Round "1"]
[Result "1-0"]
[Date "2026.09.07"]
[Site "Test"]
[Event "Oracle A"]

1. e4 {keep comment} e5 (1... c5 {keep variation}) 2. Nf3 Nc6 1-0
'''

_GAME_B = '''[Event "Oracle B"]
[Site "Test"]
[Date "2026.09.07"]
[Round "2"]
[White "Gamma"]
[Black "Delta"]
[Result "1/2-1/2"]

1. d4 d5 2. c4 e6 1/2-1/2
'''

_GAME_A_CHANGED = '''[Event "Oracle A"]
[Site "Test"]
[Date "2026.09.07"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 c5 2. Nf3 Nc6 1-0
'''


class CbfCbiOracleQualificationTests(unittest.TestCase):
    def _config(self) -> ExternalCbfCbiReaderConfig:
        return ExternalCbfCbiReaderConfig(
            cbh2si4_executable=Path("cbh2si4"),
            cbh2si4_sha256="1" * 64,
            tcscid_executable=Path("tcscid"),
            tcscid_sha256="2" * 64,
            scidpgn_script=Path("scidpgn.tcl"),
            scidpgn_sha256="3" * 64,
            max_games=10,
        )

    def _decoded(self, pgn: str) -> CbfCbiReadResult:
        return CbfCbiReadResult(
            source=None,  # type: ignore[arg-type] - backend is mocked in these tests
            source_family_sha256="a" * 64,
            cbh2si4_sha256="1" * 64,
            tcscid_sha256="2" * 64,
            scidpgn_sha256="3" * 64,
            games=tuple(parse_games(pgn)),
            canonical_roundtrip_verified=True,
        )

    def test_equivalent_pgn_whitespace_and_tag_order_return_exact_evidence(self) -> None:
        config = self._config()
        oracle = _GAME_A_REORDERED.encode("utf-8")
        with patch(
            "acs.cbf_cbi_qualification.read_cbf_cbi_external",
            return_value=self._decoded(_GAME_A),
        ):
            result = qualify_cbf_cbi_against_pgn_oracle(
                "sample.cbf",
                oracle,
                config,
            )
        self.assertTrue(result.exact_semantic_match)
        self.assertTrue(result.canonical_roundtrip_verified)
        self.assertEqual(result.decoded_game_count, 1)
        self.assertEqual(result.oracle_game_count, 1)
        self.assertEqual(result.oracle_sha256, sha256(oracle).hexdigest())
        self.assertEqual(result.identity_schema_version, IDENTITY_SCHEMA_VERSION)
        self.assertRegex(result.semantic_multiset_sha256, r"^[0-9a-f]{64}$")

    def test_database_order_is_not_a_false_semantic_mismatch(self) -> None:
        config = self._config()
        decoded = self._decoded(_GAME_A + "\n" + _GAME_B)
        oracle = (_GAME_B + "\n" + _GAME_A_REORDERED).encode("utf-8")
        with patch(
            "acs.cbf_cbi_qualification.read_cbf_cbi_external",
            return_value=decoded,
        ):
            result = qualify_cbf_cbi_against_pgn_oracle(
                "sample.cbf",
                oracle,
                config,
            )
        self.assertEqual(result.decoded_game_count, 2)
        self.assertEqual(result.oracle_game_count, 2)
        self.assertTrue(result.exact_semantic_match)

    def test_changed_game_fails_closed(self) -> None:
        config = self._config()
        with patch(
            "acs.cbf_cbi_qualification.read_cbf_cbi_external",
            return_value=self._decoded(_GAME_A),
        ):
            with self.assertRaises(CbfCbiOracleQualificationError) as caught:
                qualify_cbf_cbi_against_pgn_oracle(
                    "sample.cbf",
                    _GAME_A_CHANGED.encode("utf-8"),
                    config,
                )
        self.assertEqual(
            caught.exception.code,
            CbfCbiOracleCode.ORACLE_SEMANTIC_MISMATCH,
        )

    def test_duplicate_multiplicity_must_match(self) -> None:
        config = self._config()
        with patch(
            "acs.cbf_cbi_qualification.read_cbf_cbi_external",
            return_value=self._decoded(_GAME_A + "\n" + _GAME_A),
        ):
            with self.assertRaises(CbfCbiOracleQualificationError) as caught:
                qualify_cbf_cbi_against_pgn_oracle(
                    "sample.cbf",
                    _GAME_A.encode("utf-8"),
                    config,
                )
        self.assertEqual(
            caught.exception.code,
            CbfCbiOracleCode.ORACLE_SEMANTIC_MISMATCH,
        )

    def test_invalid_oracle_encoding_fails_before_semantic_acceptance(self) -> None:
        config = self._config()
        with patch(
            "acs.cbf_cbi_qualification.read_cbf_cbi_external",
            return_value=self._decoded(_GAME_A),
        ):
            with self.assertRaises(CbfCbiOracleQualificationError) as caught:
                qualify_cbf_cbi_against_pgn_oracle(
                    "sample.cbf",
                    b"\xff\xfe\xfd",
                    config,
                )
        self.assertEqual(caught.exception.code, CbfCbiOracleCode.ORACLE_INVALID)

    def test_empty_oracle_cannot_qualify_support(self) -> None:
        config = self._config()
        with patch(
            "acs.cbf_cbi_qualification.read_cbf_cbi_external",
            return_value=self._decoded(""),
        ):
            with self.assertRaises(CbfCbiOracleQualificationError) as caught:
                qualify_cbf_cbi_against_pgn_oracle(
                    "sample.cbf",
                    b"",
                    config,
                )
        self.assertEqual(caught.exception.code, CbfCbiOracleCode.ORACLE_INVALID)


if __name__ == "__main__":
    unittest.main()
