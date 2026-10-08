"""Real Section 40 Windows/Linux owner-test ingress through existing runtime seam."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools import revised_section40_offline_test_library as corpus
from tools import revised_section40_user_library_seed_bridge as bridge
from acs.acsdb import AcsDatabase
from acs.user_library_seed import (
    import_user_library_seed, load_user_library_seed,
)


class RevisedSection40RuntimeSeedTests(unittest.TestCase):
    def test_real_collection_is_loadable_by_unmodified_program_library(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            src = base / "actual-offline-test.zip"
            output = base / "owner-runtime-seed.zip"
            corpus.build_collection("TEST_BUILD", src)
            report = bridge.build_owner_test_seed(src, output)
            self.assertTrue(output.exists())
            self.assertEqual(report["source_count"], 2)
            self.assertEqual(report["game_count"], 516)
            self.assertFalse(report["section40_done"])
            self.assertEqual(report["archive_sha256"],
                             hashlib.sha256(output.read_bytes()).hexdigest())
            package = base / "mock-executable-directory"
            with zipfile.ZipFile(output) as z:
                self.assertEqual(sorted(z.namelist()), [
                    "release-content/user-library-seed/manifest.json",
                    "release-content/user-library-seed/section40-lichess-4-annotated-games.pgn",
                    "release-content/user-library-seed/section40-stockfish-512-real-games.pgn",
                ])
                for name in z.namelist():
                    path = package.joinpath(*name.split("/"))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(z.read(name))
            seed = load_user_library_seed(package / "release-content" / "user-library-seed")
            with AcsDatabase(base / "persisted-library.acsdb") as db:
                initial = import_user_library_seed(db, seed)
                self.assertEqual(initial.game_count, 516)
                self.assertEqual(initial.source_count, 2)
                self.assertEqual(initial.reused_source_count, 0)
            with AcsDatabase(base / "persisted-library.acsdb") as reopened:
                again = import_user_library_seed(reopened, seed)
                self.assertEqual(again.source_count, 2)
                self.assertEqual(again.reused_source_count, 2)
                reopened.verify_integrity()

    def test_public_release_is_not_disguised_as_owner_test_ingress(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            src = base / "public.zip"
            dst = base / "must-not-exist.zip"
            corpus.build_collection("PUBLIC_RELEASE", src)
            with self.assertRaises(corpus.OfflineCollectionError):
                bridge.build_owner_test_seed(src, dst)
            self.assertFalse(dst.exists())

    def test_owner_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            original = base / "existing.zip"
            original.write_bytes(b"OWNER DATA")
            with self.assertRaisesRegex(corpus.OfflineCollectionError, "already exists"):
                bridge.build_owner_test_seed(base / "absent.zip", original)
            self.assertEqual(original.read_bytes(), b"OWNER DATA")

    def test_bad_issuer_receipts_are_rejected_before_seed_creation(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            corrupted = base / "tampered.zip"
            with zipfile.ZipFile(corrupted, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("catalog/checksums.json", "[]")
                z.writestr("catalog/materials.json", '{"profile":"TEST_BUILD"}')
                z.writestr("library/real-stockfish-first-512.pgn", "1. e4 e5 *")
            with self.assertRaises(corpus.OfflineCollectionError):
                bridge.build_owner_test_seed(corrupted, base / "reject.zip")
            self.assertFalse((base / "reject.zip").exists())

    def test_self_signed_receipts_cannot_replace_pinned_original_games(self):
        """Checksums within one archive cannot replace independent CC0 originals."""
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            original = base / "real-builder.zip"
            corpus.build_collection("TEST_BUILD", original)
            with zipfile.ZipFile(original) as source:
                members = [(info, source.read(info.filename))
                           for info in source.infolist()]
            for member_path, sha_field, exception in (
                (bridge._ADVANCED_PGN,
                 "advanced_annotated_source_sha256",
                 "independently verified original"),
                (bridge._LIBRARY_PGN,
                 "derivative_pgn_sha256",
                 "independently verified 512-game source"),
            ):
                with self.subTest(source=member_path):
                    forged = base / ("counterfeit-" + member_path.rsplit("/", 1)[-1] + ".zip")
                    output = base / ("rejected-" + member_path.rsplit("/", 1)[-1] + ".zip")
                    altered = {
                        info.filename: (data + b"\n" if info.filename == member_path else data)
                        for info, data in members
                    }
                    counterfeit_hash = hashlib.sha256(altered[member_path]).hexdigest()
                    manifest = json.loads(altered["catalog/materials.json"])
                    manifest["real_import_readback"][sha_field] = counterfeit_hash
                    altered["catalog/materials.json"] = (
                        json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n"
                    ).encode("utf-8")
                    receipts = json.loads(altered["catalog/checksums.json"])
                    for record in receipts:
                        payload = altered[record["path"]]
                        record["sha256"] = hashlib.sha256(payload).hexdigest()
                        record["bytes"] = len(payload)
                    altered["catalog/checksums.json"] = (
                        json.dumps(receipts, ensure_ascii=False, sort_keys=True) + "\n"
                    ).encode("utf-8")
                    with zipfile.ZipFile(forged, "w") as target:
                        for info, _ in members:
                            target.writestr(info, altered[info.filename])
                    with self.assertRaisesRegex(
                        corpus.OfflineCollectionError, exception
                    ):
                        bridge.build_owner_test_seed(forged, output)
                    self.assertFalse(output.exists())

    def test_zip_slip_is_rejected(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            corrupted = base / "traversal.zip"
            with zipfile.ZipFile(corrupted, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("../evil.pgn", "1. e4 e5 *")
                z.writestr("catalog/checksums.json", "[]")
            with self.assertRaises(corpus.OfflineCollectionError):
                bridge.build_owner_test_seed(corrupted, base / "reject.zip")
            self.assertFalse((base / "reject.zip").exists())


if __name__ == "__main__":
    unittest.main()
