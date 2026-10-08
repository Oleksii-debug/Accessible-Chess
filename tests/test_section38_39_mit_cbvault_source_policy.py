"""Independent MIT CBH oracle only: no permission to claim CBF/2CBH/CBONE."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.gametree import parse_games
from acs.lawful_corpus_registry import LawfulCorpusError
from tools import section38_39_mit_cbvault_oracle as m


class MITCbvaultNoFalsePassTests(unittest.TestCase):
    def test_pinned_mit_commit_and_explicit_unsupported_extensions(self):
        self.assertEqual(m.BACKEND_COMMIT,
                         "3e56040fd2c38fdc2c8a25b4aff4d7ead2c5154b")
        self.assertEqual(m.BACKEND_VERSION, "0.1.4")
        self.assertEqual(m.BACKEND_LICENSE, "MIT")
        self.assertEqual(m.UPSTREAM_COMMIT,
                         "9641c5c3949d8fb210b17dd9aa54455645843696")

    def test_missing_or_non_hash_identity_refuses_before_external_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-executable"
            root = Path(tmp)
            for expected in ("", "not-a-sha", "a" * 39, "1" * 64):
                with self.subTest(value=expected):
                    with self.assertRaises(LawfulCorpusError):
                        m.qualify_mit_cbvault(
                            backend_binary=missing,
                            original_libcbh_checkout=root,
                            backend_checkout=root,
                            expected_product_head=expected,
                        )
            with self.assertRaises(LawfulCorpusError):
                m._bounded_file_digest(missing, max_bytes=100)

    def test_mutated_external_binary_detected_by_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "fake-program"
            file.write_bytes(b"safe test bytes")
            pristine = m._bounded_file_digest(file, max_bytes=50)
            self.assertEqual(pristine[0], hashlib.sha256(b"safe test bytes").hexdigest())
            file.write_bytes(b"corrupt test bytes")
            self.assertNotEqual(m._bounded_file_digest(file, max_bytes=50), pristine)
            with self.assertRaises(LawfulCorpusError):
                m._bounded_file_digest(file, max_bytes=3)

    def test_canonical_gametree_signature_is_about_annotations_not_counts(self):
        simple = (
            '[Event "Expert example"]\n[White "A"]\n[Black "B"]\n'
            '[Result "*"]\n\n1. d4 d5 *'
        )
        altered = simple.replace("1. d4 d5", "1. e4 e5")
        prior = tuple(parse_games(simple))
        different = tuple(parse_games(altered))
        self.assertEqual(len(prior), len(different))
        self.assertNotEqual(m._original_games_signature(prior),
                            m._original_games_signature(different))

    def test_external_cbvault_cannot_false_pass_lost_annotations_or_headers(self):
        # Same moves and result do not prove that publisher commentary,
        # event/source identity, or study variations survived a decoder.
        origin = (
            '[Event "Advanced master training"]\n'
            '[White "Master A"]\n'
            '[Black "Master B"]\n'
            '[Annotator "Author of notes"]\n'
            '[Result "*"]\n\n'
            '1. d4 {Critical plan} d5 $1 2. c4 (2. Nf3 {Quiet alternative}) e6 *'
        )
        original = tuple(parse_games(origin))
        self.assertEqual(len(original), 1)
        mutations = (
            origin.replace('Advanced master training', 'Unrelated event'),
            origin.replace('[Annotator "Author of notes"]\n', ''),
            origin.replace('{Critical plan}', ''),
            origin.replace(' $1', ''),
            origin.replace(' (2. Nf3 {Quiet alternative})', ''),
        )
        for damaged in mutations:
            with self.subTest(damaged=damaged[:55]):
                parsed = tuple(parse_games(damaged))
                self.assertEqual(len(parsed), 1)
                self.assertNotEqual(
                    m._original_games_signature(original),
                    m._original_games_signature(parsed),
                    "independent CBH importer lost original publisher semantics",
                )

    def test_line_level_comments_are_part_of_complete_original_semantics(self):
        from acs.gametree import Comment, MoveNode, PgnGame, VariationLine
        initial = PgnGame(
            tags={"White": "Master A", "Black": "Master B", "Result": "*"},
            line=VariationLine(moves=[MoveNode(san="e4")], result="*"),
        )
        with_comment = PgnGame(
            tags=dict(initial.tags),
            line=VariationLine(
                moves=[MoveNode(san="e4")],
                leading_comments=[Comment(text="Deep original study context")],
                result="*",
            ),
        )
        self.assertNotEqual(
            m._original_games_signature((initial,)),
            m._original_games_signature((with_comment,)),
        )

    def test_real_source_mode_does_not_succeed_when_cli_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "stub"
            source = Path(tmp) / "sample.cbh"
            binary.write_bytes(b"placeholder")
            source.write_bytes(b"source")
            with patch.object(m.subprocess, "Popen") as constructor:
                child = constructor.return_value
                child.poll.return_value = 0
                child.returncode = 0
                with self.assertRaisesRegex(LawfulCorpusError, "no bounded complete PGN"):
                    m._run_external_pgn(binary, source)
                child.wait.assert_called_once()
                child.kill.assert_not_called()

    def test_external_decoder_stdout_is_file_bounded_and_exact_bytes(self):
        import os
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as tmp:
            binary, source = Path(tmp) / "safe-decoder", Path(tmp) / "original.cbh"
            binary.write_bytes(b"stub")
            source.write_bytes(b"original")
            exact = b'[Event "Original expert"]\n\n1. e4 e5 *\n'
            observed = []

            def safe_stub(args, **kwargs):
                self.assertIsNot(kwargs["stdout"], m.subprocess.PIPE)
                self.assertIsNot(kwargs["stderr"], m.subprocess.PIPE)
                self.assertIs(kwargs["shell"], False)
                observed.append(tuple(args))
                kwargs["stdout"].write(exact)
                kwargs["stdout"].flush()
                child = MagicMock()
                child.poll.return_value = 0
                child.returncode = 0
                return child

            with patch.object(m.subprocess, "Popen", side_effect=safe_stub):
                self.assertEqual(m._run_external_pgn(binary, source), exact)
            self.assertEqual(observed, [(str(binary), "pgn", str(source))])

            def oversized_stub(args, **kwargs):
                os.ftruncate(kwargs["stdout"].fileno(), m._MAX_PGN + 1)
                child = MagicMock()
                child.poll.return_value = 0
                child.returncode = 0
                return child

            with patch.object(m.subprocess, "Popen", side_effect=oversized_stub):
                with self.assertRaisesRegex(LawfulCorpusError, "bounded complete PGN"):
                    m._run_external_pgn(binary, source)

            def stderr_bomb(args, **kwargs):
                os.ftruncate(kwargs["stderr"].fileno(), 1024 * 1024 + 1)
                child = MagicMock()
                child.poll.return_value = 0
                child.returncode = 0
                return child

            with patch.object(m.subprocess, "Popen", side_effect=stderr_bomb):
                with self.assertRaisesRegex(LawfulCorpusError, "bounded complete PGN"):
                    m._run_external_pgn(binary, source)

    def test_external_decoder_timeout_kills_child_without_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "stub"
            source = Path(tmp) / "original.cbh"
            binary.write_bytes(b"stub")
            source.write_bytes(b"original")
            with patch.object(m.subprocess, "Popen") as constructor:
                child = constructor.return_value
                child.poll.return_value = None
                with patch.object(m.time, "monotonic", side_effect=[0, 46]):
                    with self.assertRaisesRegex(LawfulCorpusError, "timed out"):
                        m._run_external_pgn(binary, source)
                child.kill.assert_called_once()
                child.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
