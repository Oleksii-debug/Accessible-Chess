from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import acs.media_truth_corpus as truth_module
from acs.media_preprocess import (
    AdaptiveSamplingPolicy,
    BoardOrientation,
    FrameDisposition,
    PreprocessContractError,
    PreprocessErrorCode,
    PreprocessStatus,
    RecordedMediaPreprocessPlan,
    RecordedMediaSourceRevision,
)
from acs.media_preprocess_executor import RecordedMediaPreprocessExecutor
from acs.media_truth_corpus import (
    RecordedMediaTruthCorpus,
    TruthCorpusBoardVisionPort,
    TRUTH_CORPUS_LICENSE,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "recorded_media_truth"


class RecordedMediaTruthCorpusTests(unittest.TestCase):
    def corpus(self) -> RecordedMediaTruthCorpus:
        return RecordedMediaTruthCorpus.load(FIXTURE_ROOT)

    def test_manifest_is_first_party_hash_locked_and_covers_required_visual_states(self):
        corpus = self.corpus()
        self.assertEqual(corpus.license, TRUTH_CORPUS_LICENSE)
        self.assertIn("Project-authored synthetic", corpus.provenance)
        self.assertEqual(corpus.source_id, "synthetic-recorded-media-v1")
        self.assertEqual(corpus.source_revision, "truth-corpus-source-v1")
        self.assertEqual(corpus.board_revision, "truth-corpus-board-v1")
        self.assertEqual(
            [frame.timestamp_ms for frame in corpus.frames],
            [0, 1000, 2000, 3000, 4000],
        )
        self.assertEqual(
            [frame.evidence.disposition for frame in corpus.frames],
            [
                FrameDisposition.STABLE,
                FrameDisposition.TRANSITION,
                FrameDisposition.STABLE,
                FrameDisposition.OCCLUDED,
                FrameDisposition.AMBIGUOUS,
            ],
        )
        self.assertEqual(corpus.frames[0].evidence.orientation, BoardOrientation.WHITE_BOTTOM)
        self.assertEqual(corpus.frames[2].evidence.orientation, BoardOrientation.BLACK_BOTTOM)
        self.assertEqual(len(corpus.frames[0].evidence.square_confidence), 64)
        self.assertEqual(len(corpus.frames[4].evidence.square_confidence), 64)
        for frame in corpus.frames:
            data = corpus.asset_bytes(frame.timestamp_ms)
            self.assertTrue(data.startswith(b"<svg "))
            self.assertNotIn(b"<script", data.lower())
            self.assertNotIn(b"href=", data.lower())

    def test_fixture_port_drives_exact_executor_plan_without_network_or_chess_authority(self):
        corpus = self.corpus()
        source = RecordedMediaSourceRevision(
            corpus.source_id,
            corpus.source_revision,
            corpus.source_ref,
            corpus.duration_ms,
        )
        plan = RecordedMediaPreprocessPlan.build(
            source,
            board_revision=corpus.board_revision,
            policy=AdaptiveSamplingPolicy(1000, 200, 0),
        )
        port = TruthCorpusBoardVisionPort(corpus)
        executor = RecordedMediaPreprocessExecutor(plan, port)
        dispositions = []
        while executor.status is PreprocessStatus.RUNNING:
            step = executor.step_board()
            dispositions.append(step.board_evidence.disposition)
        self.assertIs(executor.status, PreprocessStatus.COMPLETE)
        self.assertEqual(
            dispositions,
            [
                FrameDisposition.STABLE,
                FrameDisposition.TRANSITION,
                FrameDisposition.STABLE,
                FrameDisposition.OCCLUDED,
                FrameDisposition.AMBIGUOUS,
            ],
        )

    def test_asset_tamper_fails_before_fixture_truth_is_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "corpus"
            shutil.copytree(FIXTURE_ROOT, copied)
            asset = copied / "stable-white.svg"
            asset.write_text(asset.read_text(encoding="utf-8") + "<!-- tampered -->\n", encoding="utf-8")
            with self.assertRaises(PreprocessContractError) as caught:
                RecordedMediaTruthCorpus.load(copied)
            self.assertEqual(caught.exception.code, PreprocessErrorCode.INVALID)

    def test_manifest_path_traversal_and_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "corpus"
            shutil.copytree(FIXTURE_ROOT, copied)
            manifest = json.loads((copied / "manifest.json").read_text(encoding="utf-8"))
            manifest["frames"][0]["asset"] = "../stable-white.svg"
            (copied / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(PreprocessContractError):
                RecordedMediaTruthCorpus.load(copied)

        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "corpus"
            shutil.copytree(FIXTURE_ROOT, copied)
            text = (copied / "manifest.json").read_text(encoding="utf-8")
            text = text.replace(
                '"schema": "accessible-chess.recorded-media-truth-corpus",',
                '"schema": "accessible-chess.recorded-media-truth-corpus",\n'
                '  "schema": "attacker",',
                1,
            )
            (copied / "manifest.json").write_text(text, encoding="utf-8")
            with self.assertRaises(PreprocessContractError):
                RecordedMediaTruthCorpus.load(copied)

    def test_wrong_source_or_missing_timestamp_fails_closed(self):
        corpus = self.corpus()
        port = TruthCorpusBoardVisionPort(corpus)
        with self.assertRaises(PreprocessContractError) as caught:
            port.observe("other-source", 0)
        self.assertEqual(caught.exception.code, PreprocessErrorCode.SOURCE_MISMATCH)
        with self.assertRaises(PreprocessContractError) as caught:
            port.observe(corpus.source_ref, 999)
        self.assertEqual(caught.exception.code, PreprocessErrorCode.REQUEST_MISMATCH)

    def test_truth_corpus_module_has_no_chess_rules_or_network_authority(self):
        tree = ast.parse(inspect.getsource(truth_module))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        self.assertTrue(
            roots.isdisjoint(
                {
                    "chess",
                    "chesscore",
                    "gametree",
                    "pgn",
                    "requests",
                    "urllib",
                    "http",
                    "socket",
                    "subprocess",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
