import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from acs.gametree import parse_games, serialize_games
import acs.pgn_service as pgn_service_module
from acs.import_contract import ImportQuality
from acs.pgn_service import (
    PgnConcurrentWriteError,
    PgnFileImporter,
    PgnPublicationUnverifiedError,
    PgnUnsafePathError,
    export_game_atomic,
    open_pgn,
    save_pgn_atomic,
)


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

    def test_open_windows_1251_preserves_cyrillic_comments_and_rav(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy-russian-book.pgn"
            source = (
                '[Event "Русская шахматная книга"]\n'
                '[Site "Киев"]\n'
                '[Result "*"]\n\n'
                '1. e4 {главный план} e5 '
                '(1... c5 $1 {сицилианская защита} 2. Nf3) '
                '2. Nf3 *\n'
            )
            path.write_bytes(source.encode("cp1251"))

            opened = open_pgn(path)

            self.assertEqual(opened.total_games, 1)
            self.assertEqual(opened.games[0].tags["Event"], "Русская шахматная книга")
            self.assertEqual(opened.games[0].tags["Site"], "Киев")
            self.assertEqual(
                opened.games[0].line.moves[0].comments_after[0].text,
                "главный план",
            )
            variation = opened.games[0].line.moves[1].variations[0]
            self.assertEqual(variation.moves[0].san, "c5")
            self.assertEqual(
                variation.moves[0].comments_after[0].text,
                "сицилианская защита",
            )
            self.assertTrue(
                any(
                    warning.startswith("Legacy Windows-1251 PGN was decoded losslessly")
                    for warning in opened.global_warnings
                )
            )
            self.assertFalse(
                any("bytes were replaced" in warning for warning in opened.global_warnings)
            )

    def test_malformed_cp1251_like_source_never_leaks_codec_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "malformed-legacy-looking.pgn"
            prefix = (
                '[Event "Русский тест"]\n'
                '[Result "*"]\n\n'
                '1. e4 {'
            ).encode("cp1251")
            path.write_bytes(prefix + b"bad-" + bytes((0x98,)) + b"-byte} *\\n")

            opened = open_pgn(path)

            self.assertEqual(opened.total_games, 1)
            self.assertTrue(
                any(
                    warning.startswith("Invalid UTF-8 bytes were replaced")
                    for warning in opened.global_warnings
                )
            )
            self.assertFalse(
                any(
                    warning.startswith("Legacy Windows-1251 PGN was decoded losslessly")
                    for warning in opened.global_warnings
                )
            )

    def test_atomic_save_round_trips_rich_structure(self):
        games = parse_games(RICH_PGN)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.pgn"
            saved = save_pgn_atomic(path, games)
            self.assertEqual(saved.sha256, open_pgn(path).source.sha256)
            self.assertEqual(serialize_games(open_pgn(path).games), serialize_games(games))

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

    def test_expected_hash_boundary_rejects_noncanonical_or_active_digest_before_mutation(self):
        games = parse_games('[Event "Prepared"]\n[Result "*"]\n\n1. e4 *')

        class HostileDigest(str):
            touched = False

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("digest equality hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("digest iteration hook must not execute")

        invalid_values = (
            HostileDigest("0" * 64),
            True,
            0,
            "0" * 63,
            "0" * 65,
            "A" * 64,
            "g" * 64,
        )
        for index, digest in enumerate(invalid_values):
            with self.subTest(index=index, digest_type=type(digest).__name__):
                with tempfile.TemporaryDirectory() as tmp:
                    parent = Path(tmp) / "not-created"
                    path = parent / "out.pgn"
                    with self.assertRaises((TypeError, ValueError)):
                        save_pgn_atomic(
                            path,
                            games,
                            overwrite=True,
                            expected_sha256=digest,  # type: ignore[arg-type]
                        )
                    self.assertFalse(parent.exists())
        self.assertFalse(HostileDigest.touched)

    def test_expected_hash_preserves_writer_racing_at_replace_boundary(self):
        games = parse_games('[Event "Original"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared.pgn"
            path.write_text('[Event "Original"]\n[Result "*"]\n\n1. e4 *\n', encoding="utf-8")
            opened = open_pgn(path)
            real_replace = pgn_service_module._replace_published_path

            def racing_replace(src, dst):
                Path(dst).write_text(
                    '[Event "Concurrent writer"]\n[Result "*"]\n\n1. d4 *\n',
                    encoding="utf-8",
                )
                return real_replace(src, dst)

            with mock.patch("acs.pgn_service._replace_published_path", side_effect=racing_replace):
                with self.assertRaises(PgnConcurrentWriteError):
                    save_pgn_atomic(
                        path,
                        games,
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )
            self.assertIn("Concurrent writer", path.read_text(encoding="utf-8"))

    def test_no_overwrite_publication_is_atomic_no_clobber(self):
        games = parse_games('[Event "Our export"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "new-shared.pgn"
            real_link = pgn_service_module._publish_no_clobber

            def racing_link(src, dst, *args, **kwargs):
                Path(dst).write_text(
                    '[Event "Created by another writer"]\n[Result "*"]\n\n1. d4 *\n',
                    encoding="utf-8",
                )
                return real_link(src, dst, *args, **kwargs)

            with mock.patch("acs.pgn_service._publish_no_clobber", side_effect=racing_link):
                with self.assertRaises(FileExistsError):
                    save_pgn_atomic(path, games, overwrite=False)
            self.assertIn("Created by another writer", path.read_text(encoding="utf-8"))

    def test_export_parent_replacement_before_payload_fails_closed(self):
        games = parse_games('[Event "Prepared"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "chosen"
            parent.mkdir()
            moved = root / "chosen-original"
            path = parent / "out.pgn"
            consumed = False
            real_named_temporary_file = tempfile.NamedTemporaryFile

            def guarded_games():
                nonlocal consumed
                consumed = True
                yield from games

            def replace_parent_before_temp_open(*args, **kwargs):
                parent.rename(moved)
                parent.mkdir()
                return real_named_temporary_file(*args, **kwargs)

            with mock.patch(
                "acs.pgn_service.tempfile.NamedTemporaryFile",
                side_effect=replace_parent_before_temp_open,
            ):
                with self.assertRaises(PgnUnsafePathError):
                    save_pgn_atomic(path, guarded_games())

            self.assertFalse(consumed)
            self.assertFalse(path.exists())
            self.assertFalse((moved / "out.pgn").exists())
            self.assertEqual(list(parent.glob("*.tmp")), [])
            self.assertEqual(list(moved.glob("*.tmp")), [])

    def test_export_parent_replacement_after_commit_cannot_report_false_success(self):
        games = parse_games('[Event "Prepared"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "chosen"
            parent.mkdir()
            moved = root / "chosen-original"
            path = parent / "out.pgn"

            import acs.pgn_service as pgn_service_module

            real_fingerprint = pgn_service_module.fingerprint

            def replace_parent_during_final_fingerprint(candidate, *args, **kwargs):
                parent.rename(moved)
                parent.mkdir()
                path.write_text(
                    '[Event "Replacement path"]\n[Result "*"]\n\n1. d4 *\n',
                    encoding="utf-8",
                )
                return real_fingerprint(candidate, *args, **kwargs)

            with mock.patch(
                "acs.pgn_service.fingerprint",
                side_effect=replace_parent_during_final_fingerprint,
            ):
                with self.assertRaises(PgnUnsafePathError):
                    save_pgn_atomic(path, games)

            self.assertIn(
                "Prepared",
                (moved / "out.pgn").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Replacement path",
                path.read_text(encoding="utf-8"),
            )

    def test_post_commit_cleanup_base_exceptions_leave_committed_bytes_authoritative(self):
        class CleanupAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "committed.pgn"
            destination.write_text("committed bytes", encoding="utf-8")
            redundant = Path(tmp) / "committed.pgn.redundant"
            redundant.write_text("redundant bytes", encoding="utf-8")

            with mock.patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=CleanupAbort("Path.unlink cleanup aborted"),
            ):
                with mock.patch(
                    "acs.pgn_service.os.unlink",
                    side_effect=CleanupAbort("os.unlink cleanup aborted"),
                ):
                    pgn_service_module._cleanup_redundant_link_after_commit(redundant)

            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                "committed bytes",
            )
            self.assertTrue(redundant.exists())
            redundant.unlink()

    def test_post_publish_namespace_base_exception_is_publication_unverified(self):
        class DurabilityAbort(BaseException):
            pass

        games = parse_games('[Event "Prepared"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "post-publish-abort.pgn"

            with mock.patch(
                "acs.pgn_service._sync_published_namespace",
                side_effect=DurabilityAbort("directory sync aborted"),
            ):
                with self.assertRaises(PgnPublicationUnverifiedError):
                    save_pgn_atomic(path, games)

            self.assertTrue(path.exists())
            self.assertIn("Prepared", path.read_text(encoding="utf-8"))

    def test_expected_hash_verification_base_exception_preserves_recovery_snapshot(self):
        class VerificationAbort(BaseException):
            pass

        games = parse_games('[Event "Our save"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared-verification-abort.pgn"
            path.write_text(
                '[Event "Original"]\n[Result "*"]\n\n1. d4 *\n',
                encoding="utf-8",
            )
            opened = open_pgn(path)
            real_current_sha256 = pgn_service_module._current_sha256
            snapshot_reads = 0

            def abort_second_snapshot_verification(candidate):
                nonlocal snapshot_reads
                candidate = Path(candidate)
                if ".cas-" in candidate.name and candidate.suffix == ".bak":
                    snapshot_reads += 1
                    if snapshot_reads == 2:
                        raise VerificationAbort("post-replace snapshot verification aborted")
                return real_current_sha256(candidate)

            with mock.patch(
                "acs.pgn_service._current_sha256",
                side_effect=abort_second_snapshot_verification,
            ):
                with self.assertRaises(PgnPublicationUnverifiedError):
                    save_pgn_atomic(
                        path,
                        games,
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )

            snapshots = list(Path(tmp).glob("shared-verification-abort.pgn.cas-*.bak"))
            self.assertEqual(len(snapshots), 1)
            self.assertIn("Original", snapshots[0].read_text(encoding="utf-8"))
            self.assertIn("Our save", path.read_text(encoding="utf-8"))

    def test_expected_hash_rollback_base_exception_preserves_newer_writer_snapshot(self):
        class RollbackAbort(BaseException):
            pass

        games = parse_games('[Event "Our save"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared-rollback-abort.pgn"
            path.write_text(
                '[Event "Original"]\n[Result "*"]\n\n1. d4 *\n',
                encoding="utf-8",
            )
            opened = open_pgn(path)
            real_replace = pgn_service_module._replace_published_path
            replace_calls = 0

            def abort_rollback(source, destination):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 1:
                    Path(destination).write_text(
                        '[Event "Concurrent writer"]\n[Result "*"]\n\n1. c4 *\n',
                        encoding="utf-8",
                    )
                    return real_replace(source, destination)
                raise RollbackAbort("rollback publication aborted")

            with mock.patch(
                "acs.pgn_service._replace_published_path",
                side_effect=abort_rollback,
            ):
                with self.assertRaises(PgnPublicationUnverifiedError):
                    save_pgn_atomic(
                        path,
                        games,
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )

            self.assertEqual(replace_calls, 2)
            snapshots = list(Path(tmp).glob("shared-rollback-abort.pgn.cas-*.bak"))
            self.assertEqual(len(snapshots), 1)
            self.assertIn("Concurrent writer", snapshots[0].read_text(encoding="utf-8"))
            self.assertIn("Our save", path.read_text(encoding="utf-8"))

    def test_pre_publish_failure_survives_temp_cleanup_base_exception(self):
        class CleanupAbort(BaseException):
            pass

        games = parse_games('[Event "Prepared"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pre-publish-cleanup-abort.pgn"
            real_unlink = Path.unlink

            def abort_temp_cleanup(candidate, *args, **kwargs):
                candidate = Path(candidate)
                if candidate.name.startswith(path.name + ".") and candidate.suffix == ".tmp":
                    raise CleanupAbort("temporary cleanup aborted")
                return real_unlink(candidate, *args, **kwargs)

            def primary_failure():
                raise RuntimeError("primary pre-publication failure")

            with mock.patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=abort_temp_cleanup,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "primary pre-publication failure",
                ):
                    save_pgn_atomic(
                        path,
                        games,
                        pre_publish_check=primary_failure,
                    )

            self.assertFalse(path.exists())
            residual = list(Path(tmp).glob("pre-publish-cleanup-abort.pgn.*.tmp"))
            self.assertEqual(len(residual), 1)
            real_unlink(residual[0])

    def test_pre_publish_check_aborts_after_fsync_without_publication(self):
        games = parse_games('[Event "Prepared"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cancel-before-publish.pgn"
            observed_sizes = []

            def abort_after_fsync():
                temps = list(Path(tmp).glob("*.tmp"))
                self.assertEqual(len(temps), 1)
                observed_sizes.append(temps[0].stat().st_size)
                self.assertGreater(observed_sizes[-1], 0)
                self.assertFalse(path.exists())
                raise RuntimeError("cancel before publication")

            with self.assertRaisesRegex(RuntimeError, "cancel before publication"):
                save_pgn_atomic(
                    path,
                    games,
                    pre_publish_check=abort_after_fsync,
                )

            self.assertTrue(observed_sizes)
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_invalid_pre_publish_check_fails_before_filesystem_mutation(self):
        games = parse_games('[Event "Prepared"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "not-created"
            path = parent / "out.pgn"
            with self.assertRaisesRegex(TypeError, "pre_publish_check must be callable"):
                save_pgn_atomic(path, games, pre_publish_check=object())
            self.assertFalse(parent.exists())

    def test_publication_cas_workflow_qualifies_exact_absorbed_product_successor(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "pgn-conversion-prepublish-cancel.yml"
        ).read_text(encoding="utf-8")
        required = (
            "PINNED_PRODUCT_SHA: ee3fe93aa379284d8af0672ae0cafb9961e88152",
            "PREDECESSOR_PGN_HEAD: 8ac3756564b4a2331df5af1062ebf5adc12e4499",
            'test "$live_product" = "$PINNED_PRODUCT_SHA"',
            'git merge-base --is-ancestor "$PREDECESSOR_PGN_HEAD" "$live_product"',
            'git merge-base --is-ancestor "$live_product" HEAD',
            'test "$(git merge-base "$live_product" HEAD)" = "$live_product"',
            "PGN_PUBLICATION_CAS_SUPERSEDED",
            "PGN_PUBLICATION_CAS_PRODUCT_MOVED",
            "'.github/workflows/pgn-conversion-prepublish-cancel.yml'",
            "'acs/pgn_service.py'",
            "'tests/test_pgn_service.py'",
            "PGN_PUBLICATION_CAS_SCOPE=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, workflow)
        self.assertNotIn("SOURCE_BASE_SHA:", workflow)
        self.assertIn(
            'test "$(git rev-parse HEAD:acs/pgn_conversion.py)" = "$(git rev-parse "$live_product:acs/pgn_conversion.py")"',
            workflow,
        )
        self.assertIn(
            'test "$(git rev-parse HEAD:acs/pgn_conversion_windows.py)" = "$(git rev-parse "$live_product:acs/pgn_conversion_windows.py")"',
            workflow,
        )

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
