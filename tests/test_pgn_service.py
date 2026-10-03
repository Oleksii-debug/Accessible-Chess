import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from acs import pgn_service as pgn_service_module
from acs.gametree import parse_games, serialize_games
from acs.import_contract import ImportQuality
from acs.pgn_service import PgnConcurrentWriteError, PgnFileError, PgnFileImporter, PgnUnsafePathError, export_game_atomic, open_pgn, save_pgn_atomic


RICH_PGN = '''[Event "Main"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 {main comment} e5 $1 (1... c5 {Sicilian} 2. Nf3) 2. Nf3 Nc6 1-0

[Event "Second"]
[Result "*"]

1. d4 d5 2. c4 *
'''


class PgnFileServiceTests(unittest.TestCase):
    def test_open_preserves_multi_game_recursive_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rich.pgn"
            path.write_text(RICH_PGN, encoding="utf-8")
            opened = open_pgn(path)
            self.assertEqual(opened.total_games, 2)
            self.assertEqual(opened.games[0].tags["Event"], "Main")
            second = opened.games[0].line.moves[1]
            self.assertEqual(second.san, "e5")
            self.assertIn("$1", second.nags)
            self.assertEqual(len(second.variations), 1)
            self.assertEqual([m.san for m in second.variations[0].moves], ["c5", "Nf3"])

    def test_atomic_save_round_trips_rich_structure(self):
        games = parse_games(RICH_PGN)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.pgn"
            saved = save_pgn_atomic(path, games)
            self.assertEqual(saved.sha256, open_pgn(path).source.sha256)
            self.assertEqual(serialize_games(open_pgn(path).games), serialize_games(games))

    def test_successful_publication_does_not_refingerprint_committed_destination(self):
        games = parse_games('[Event "Committed"]\n[Result "*"]\n\n1. e4 *')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "committed.pgn"
            real_fingerprint = pgn_service_module.fingerprint
            calls = []

            def guarded_fingerprint(candidate, *args, **kwargs):
                candidate_path = Path(candidate)
                calls.append(candidate_path)
                if candidate_path == path:
                    raise AssertionError(
                        "committed destination must not be fingerprinted after publication"
                    )
                return real_fingerprint(candidate, *args, **kwargs)

            with mock.patch(
                "acs.pgn_service.fingerprint",
                side_effect=guarded_fingerprint,
            ):
                saved = save_pgn_atomic(path, games)

            self.assertTrue(path.is_file())
            self.assertTrue(calls)
            self.assertTrue(all(candidate != path for candidate in calls))
            self.assertTrue(Path(saved.path).samefile(path))
            reopened = open_pgn(path)
            self.assertEqual(saved.size, reopened.source.size)
            self.assertEqual(saved.sha256, reopened.source.sha256)
            self.assertEqual(saved.suffix, ".pgn")
            self.assertEqual(reopened.games[0].tags["Event"], "Committed")

    def test_existing_file_is_protected_by_default(self):
        games = parse_games('[Event "A"]\n[Result "*"]\n\n1. e4 *')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.pgn"
            path.write_text("do not replace", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                save_pgn_atomic(path, games)
            self.assertEqual(path.read_text(encoding="utf-8"), "do not replace")

    def test_expected_hash_prevents_lost_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edit.pgn"
            path.write_text('[Event "A"]\n[Result "*"]\n\n1. e4 *\n', encoding="utf-8")
            opened = open_pgn(path)
            path.write_text('[Event "Other editor"]\n[Result "*"]\n\n1. d4 *\n', encoding="utf-8")
            with self.assertRaises(PgnConcurrentWriteError):
                save_pgn_atomic(path, opened.games, overwrite=True, expected_sha256=opened.source.sha256)
            self.assertIn("Other editor", path.read_text(encoding="utf-8"))

    def test_expected_hash_preserves_writer_racing_at_replace_boundary(self):
        games = parse_games('[Event "Original"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared.pgn"
            path.write_text('[Event "Original"]\n[Result "*"]\n\n1. e4 *\n', encoding="utf-8")
            opened = open_pgn(path)
            real_replace = os.replace

            def racing_replace(src, dst):
                Path(dst).write_text(
                    '[Event "Concurrent writer"]\n[Result "*"]\n\n1. d4 *\n',
                    encoding="utf-8",
                )
                return real_replace(src, dst)

            with mock.patch("acs.pgn_service.os.replace", side_effect=racing_replace):
                with self.assertRaises(PgnConcurrentWriteError):
                    save_pgn_atomic(
                        path,
                        games,
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )
            self.assertIn("Concurrent writer", path.read_text(encoding="utf-8"))

    def test_expected_hash_verification_failure_rolls_back_before_error(self):
        games = parse_games('[Event "Requested"]\n[Result "*"]\n\n1. Nf3 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "verify-failure.pgn"
            path.write_text(
                '[Event "Original"]\n[Result "*"]\n\n1. e4 *\n',
                encoding="utf-8",
            )
            opened = open_pgn(path)
            real_current_sha256 = pgn_service_module._current_sha256
            snapshot_reads = 0

            def fail_second_snapshot_read(candidate):
                nonlocal snapshot_reads
                candidate_path = Path(candidate)
                if ".cas-" in candidate_path.name:
                    snapshot_reads += 1
                    if snapshot_reads == 2:
                        raise PgnFileError("simulated post-publication verification failure")
                return real_current_sha256(candidate_path)

            with mock.patch(
                "acs.pgn_service._current_sha256",
                side_effect=fail_second_snapshot_read,
            ):
                with self.assertRaisesRegex(
                    PgnFileError,
                    "original destination was restored",
                ):
                    save_pgn_atomic(
                        path,
                        games,
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )

            self.assertIn("Original", path.read_text(encoding="utf-8"))
            self.assertNotIn("Requested", path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot_reads, 2)
            self.assertEqual(list(path.parent.glob(path.name + ".cas-*.bak")), [])
            self.assertEqual(list(path.parent.glob(path.name + ".*.tmp")), [])

    def test_expected_hash_rollback_failure_preserves_recovery_snapshot(self):
        games = parse_games('[Event "Requested"]\n[Result "*"]\n\n1. Nf3 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollback-failure.pgn"
            path.write_text(
                '[Event "Original"]\n[Result "*"]\n\n1. e4 *\n',
                encoding="utf-8",
            )
            opened = open_pgn(path)
            real_current_sha256 = pgn_service_module._current_sha256
            real_replace = os.replace
            snapshot_reads = 0

            def fail_second_snapshot_read(candidate):
                nonlocal snapshot_reads
                candidate_path = Path(candidate)
                if ".cas-" in candidate_path.name:
                    snapshot_reads += 1
                    if snapshot_reads == 2:
                        raise PgnFileError("simulated post-publication verification failure")
                return real_current_sha256(candidate_path)

            def fail_snapshot_rollback(src, dst):
                if ".cas-" in Path(src).name:
                    raise OSError("simulated rollback failure")
                return real_replace(src, dst)

            with mock.patch(
                "acs.pgn_service._current_sha256",
                side_effect=fail_second_snapshot_read,
            ), mock.patch(
                "acs.pgn_service.os.replace",
                side_effect=fail_snapshot_rollback,
            ):
                with self.assertRaisesRegex(
                    PgnFileError,
                    "recovery snapshot was preserved",
                ):
                    save_pgn_atomic(
                        path,
                        games,
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )

            self.assertIn("Requested", path.read_text(encoding="utf-8"))
            backups = list(path.parent.glob(path.name + ".cas-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertIn("Original", backups[0].read_text(encoding="utf-8"))
            self.assertEqual(snapshot_reads, 2)
            self.assertEqual(list(path.parent.glob(path.name + ".*.tmp")), [])

    def test_verification_failure_never_rolls_back_over_newer_destination(self):
        games = parse_games('[Event "Requested"]\n[Result "*"]\n\n1. Nf3 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "verification-external-write.pgn"
            path.write_text(
                '[Event "Original"]\n[Result "*"]\n\n1. e4 *\n',
                encoding="utf-8",
            )
            opened = open_pgn(path)
            real_current_sha256 = pgn_service_module._current_sha256
            snapshot_reads = 0
            external = '[Event "External"]\n[Result "*"]\n\n1. d4 *\n'

            def fail_snapshot_after_external_write(candidate):
                nonlocal snapshot_reads
                candidate_path = Path(candidate)
                if ".cas-" in candidate_path.name:
                    snapshot_reads += 1
                    if snapshot_reads == 2:
                        # A non-cooperating writer changes the newly published
                        # destination before rollback begins. The old recovery
                        # snapshot must not be allowed to overwrite these bytes.
                        path.write_text(external, encoding="utf-8")
                        raise PgnFileError("simulated verification failure")
                return real_current_sha256(candidate_path)

            with mock.patch(
                "acs.pgn_service._current_sha256",
                side_effect=fail_snapshot_after_external_write,
            ):
                with self.assertRaisesRegex(
                    PgnConcurrentWriteError,
                    "destination changed after publication",
                ):
                    save_pgn_atomic(
                        path,
                        games,
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )

            self.assertEqual(path.read_text(encoding="utf-8"), external)
            backups = list(path.parent.glob(path.name + ".cas-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertIn("Original", backups[0].read_text(encoding="utf-8"))
            self.assertEqual(snapshot_reads, 2)
            self.assertEqual(list(path.parent.glob(path.name + ".*.tmp")), [])

    def test_precommit_fingerprint_failure_does_not_publish_requested_bytes(self):
        games = parse_games('[Event "Requested"]\n[Result "*"]\n\n1. Nf3 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fingerprint-failure.pgn"
            path.write_text(
                '[Event "Original"]\n[Result "*"]\n\n1. e4 *\n',
                encoding="utf-8",
            )
            opened = open_pgn(path)
            real_fingerprint = pgn_service_module.fingerprint

            def fail_temporary_fingerprint(candidate, *args, **kwargs):
                candidate_path = Path(candidate)
                if candidate_path.suffix == ".tmp":
                    raise PgnFileError("simulated unpublished fingerprint failure")
                return real_fingerprint(candidate, *args, **kwargs)

            with mock.patch(
                "acs.pgn_service.fingerprint",
                side_effect=fail_temporary_fingerprint,
            ):
                with self.assertRaisesRegex(
                    PgnFileError,
                    "simulated unpublished fingerprint failure",
                ):
                    save_pgn_atomic(
                        path,
                        games,
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )

            self.assertIn("Original", path.read_text(encoding="utf-8"))
            self.assertNotIn("Requested", path.read_text(encoding="utf-8"))
            self.assertEqual(list(path.parent.glob(path.name + ".cas-*.bak")), [])
            self.assertEqual(list(path.parent.glob(path.name + ".*.tmp")), [])

    def test_expected_hash_commit_never_refingerprints_public_destination(self):
        games = parse_games('[Event "Requested"]\n[Result "*"]\n\n1. Nf3 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no-post-commit-readback.pgn"
            path.write_text(
                '[Event "Original"]\n[Result "*"]\n\n1. e4 *\n',
                encoding="utf-8",
            )
            opened = open_pgn(path)
            real_fingerprint = pgn_service_module.fingerprint
            real_replace = os.replace
            committed = False

            def marking_replace(src, dst):
                nonlocal committed
                result = real_replace(src, dst)
                if Path(dst) == path:
                    committed = True
                return result

            def guarded_fingerprint(candidate, *args, **kwargs):
                if committed and Path(candidate) == path:
                    raise AssertionError(
                        "committed destination must not be fingerprinted after CAS publication"
                    )
                return real_fingerprint(candidate, *args, **kwargs)

            with mock.patch(
                "acs.pgn_service.os.replace",
                side_effect=marking_replace,
            ), mock.patch(
                "acs.pgn_service.fingerprint",
                side_effect=guarded_fingerprint,
            ):
                saved = save_pgn_atomic(
                    path,
                    games,
                    overwrite=True,
                    expected_sha256=opened.source.sha256,
                )

            self.assertTrue(committed)
            self.assertIn("Requested", path.read_text(encoding="utf-8"))
            self.assertEqual(saved.sha256, open_pgn(path).source.sha256)

    def test_temporary_regular_file_swap_is_rejected_before_publication(self):
        games = parse_games('[Event "Requested"]\n[Result "*"]\n\n1. Nf3 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "destination-regular-swap.pgn"
            real_fingerprint = pgn_service_module.fingerprint
            temporary_fingerprints = 0

            def replace_bytes_after_first_fingerprint(candidate, *args, **kwargs):
                nonlocal temporary_fingerprints
                candidate_path = Path(candidate)
                result = real_fingerprint(candidate_path, *args, **kwargs)
                if candidate_path.suffix == ".tmp":
                    temporary_fingerprints += 1
                    if temporary_fingerprints == 1:
                        candidate_path.write_text(
                            '[Event "Substituted"]\n[Result "*"]\n\n1. d4 *\n',
                            encoding="utf-8",
                        )
                return result

            with mock.patch(
                "acs.pgn_service.fingerprint",
                side_effect=replace_bytes_after_first_fingerprint,
            ):
                with self.assertRaisesRegex(
                    PgnFileError,
                    "temporary file changed before publication",
                ):
                    save_pgn_atomic(path, games)

            self.assertEqual(temporary_fingerprints, 2)
            self.assertFalse(path.exists())
            self.assertEqual(list(root.glob(path.name + ".*.tmp")), [])

    @unittest.skipIf(os.name == "nt", "POSIX symlink swap regression")
    def test_temporary_symlink_swap_is_rejected_before_publication(self):
        games = parse_games('[Event "Requested"]\n[Result "*"]\n\n1. Nf3 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "destination.pgn"
            outside = root / "outside.pgn"
            outside.write_text(
                '[Event "Outside"]\n[Result "*"]\n\n1. d4 *\n',
                encoding="utf-8",
            )
            real_fingerprint = pgn_service_module.fingerprint
            swapped = False

            def swap_after_fingerprint(candidate, *args, **kwargs):
                nonlocal swapped
                candidate_path = Path(candidate)
                result = real_fingerprint(candidate_path, *args, **kwargs)
                if candidate_path.suffix == ".tmp":
                    candidate_path.unlink()
                    os.symlink(outside, candidate_path)
                    swapped = True
                return result

            with mock.patch(
                "acs.pgn_service.fingerprint",
                side_effect=swap_after_fingerprint,
            ):
                with self.assertRaises(PgnUnsafePathError):
                    save_pgn_atomic(path, games)

            self.assertTrue(swapped)
            self.assertFalse(path.exists())
            self.assertIn("Outside", outside.read_text(encoding="utf-8"))
            self.assertEqual(list(root.glob(path.name + ".*.tmp")), [])

    def test_no_overwrite_publication_is_atomic_no_clobber(self):
        games = parse_games('[Event "Our export"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "new-shared.pgn"
            real_link = os.link

            def racing_link(src, dst, *args, **kwargs):
                Path(dst).write_text(
                    '[Event "Created by another writer"]\n[Result "*"]\n\n1. d4 *\n',
                    encoding="utf-8",
                )
                return real_link(src, dst, *args, **kwargs)

            with mock.patch("acs.pgn_service.os.link", side_effect=racing_link):
                with self.assertRaises(FileExistsError):
                    save_pgn_atomic(path, games, overwrite=False)
            self.assertIn("Created by another writer", path.read_text(encoding="utf-8"))

    def test_importer_reports_warning_and_blank_damage(self):
        with tempfile.TemporaryDirectory() as tmp:
            warning = Path(tmp) / "warning.pgn"
            warning.write_text('[Event "Mismatch"]\n[Result "1-0"]\n\n1. e4 0-1\n', encoding="utf-8")
            report = PgnFileImporter().inspect(warning)
            self.assertEqual(report.records[0].quality, ImportQuality.WARNING)
            blank = Path(tmp) / "blank.pgn"
            blank.write_text("", encoding="utf-8")
            self.assertEqual(PgnFileImporter().inspect(blank).records[0].quality, ImportQuality.DAMAGED)

    def test_single_game_export_uses_atomic_path(self):
        game = parse_games('[Event "One"]\n[Result "*"]\n\n1. Nf3 *')[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.pgn"
            exported = export_game_atomic(path, game)
            self.assertEqual(exported.sha256, open_pgn(path).source.sha256)
            self.assertEqual(open_pgn(path).total_games, 1)


if __name__ == "__main__":
    unittest.main()
