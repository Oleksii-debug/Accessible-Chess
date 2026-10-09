import unittest

from acs.bookdocument import BookDocument, Diagram, Game, Heading, Paragraph, VariationTree
from acs.bookreader import BookReader


WHITE_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"
BLACK_FEN = "8/8/8/8/8/8/4K3/7k b - - 0 1"


class BookReaderTests(unittest.TestCase):
    def make_book(self):
        return BookDocument("Reader", blocks=[
            Heading(text="Part I", level=1, block_id="part-1", source_anchor="p1"),
            Paragraph(text="Intro"),
            Heading(text="Chapter", level=2, block_id="chapter", source_anchor="p2"),
            Diagram(fen=WHITE_FEN, alt_text="Kings", block_id="diagram", source_anchor="p3"),
            Game(pgn='[Result "*"]\n\n*', title="Example", block_id="game"),
            VariationTree(root_fen=BLACK_FEN, pgn="1... Kh2 *", block_id="variation"),
            Heading(text="Part II", level=1, block_id="part-2"),
        ])

    def test_location_exposes_source_heading_path_position_and_side(self):
        reader = BookReader(self.make_book())
        reader.go_to(3)
        loc = reader.location()
        self.assertEqual(loc.block_id, "diagram")
        self.assertEqual(loc.source_anchor, "p3")
        self.assertEqual(loc.heading_path, ("Part I", "Chapter"))
        self.assertEqual(loc.position_fen, WHITE_FEN)
        self.assertEqual(loc.side_to_move, "white")

    def test_semantic_navigation_preserves_linear_reading_order(self):
        reader = BookReader(self.make_book())
        self.assertEqual(reader.next_heading().block_id, "chapter")
        self.assertEqual(reader.next_position().block_id, "diagram")
        self.assertEqual(reader.next_game().block_id, "game")
        self.assertEqual(reader.next_position().block_id, "variation")
        self.assertEqual(reader.location().side_to_move, "black")
        self.assertEqual(reader.next_heading().block_id, "part-2")

    def test_return_points_restore_exact_semantic_location(self):
        reader = BookReader(self.make_book())
        reader.go_to(3)
        reader.save_return_point("analysis")
        reader.go_to(6)
        restored = reader.restore_return_point("analysis")
        self.assertEqual(restored.index, 3)
        self.assertEqual(restored.block_id, "diagram")
        self.assertEqual(restored.heading_path, ("Part I", "Chapter"))

    def test_return_point_name_raw_bound_fails_closed_for_live_and_persisted_input(self):
        reader = BookReader(self.make_book())
        reader.go_to(3)
        before = reader.snapshot()
        oversized = " " * 256 + "x"

        with self.assertRaisesRegex(ValueError, "exceeds 256"):
            reader.save_return_point(oversized)
        self.assertEqual(before, reader.snapshot())

        malformed = dict(before)
        malformed["return_points"] = {oversized: before["current_target"]}
        with self.assertRaisesRegex(ValueError, "exceeds 256"):
            BookReader.restore_snapshot(self.make_book(), malformed)

    def test_restore_rejects_snapshot_mapping_subclass_before_hooks(self):
        book = self.make_book()
        payload = BookReader(book).snapshot()

        class HostileSnapshot(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("snapshot len hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("snapshot iter hook must not execute")

            def __getitem__(self, key):
                type(self).touched = True
                raise AssertionError("snapshot getitem hook must not execute")

        hostile = HostileSnapshot()
        dict.update(hostile, payload)
        HostileSnapshot.touched = False

        with self.assertRaisesRegex(TypeError, "snapshot must be a mapping"):
            BookReader.restore_snapshot(book, hostile)
        self.assertFalse(HostileSnapshot.touched)
    def test_restore_rejects_nested_mapping_subclasses_before_hooks(self):
        book = self.make_book()
        valid = BookReader(book).snapshot()

        class HostileNested(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("nested len hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("nested iter hook must not execute")

            def __getitem__(self, key):
                type(self).touched = True
                raise AssertionError("nested getitem hook must not execute")

        for field in ("return_points", "fallback_digests"):
            snapshot = dict(valid)
            hostile = HostileNested()
            dict.update(hostile, snapshot[field])
            snapshot[field] = hostile
            HostileNested.touched = False

            with self.subTest(field=field):
                with self.assertRaisesRegex(TypeError, f"{field} must be a mapping"):
                    BookReader.restore_snapshot(book, snapshot)
                self.assertFalse(HostileNested.touched)
    def test_restore_snapshot_bounds_scalar_keys_with_canonical_dicts(self):
        book = self.make_book()
        valid = BookReader(book).snapshot()

        oversized_field = "x" * 64
        top_level = dict(valid)
        top_level.pop("fallback_digests")
        top_level[oversized_field] = {}
        with self.assertRaisesRegex(ValueError, "field name exceeds supported bound"):
            BookReader.restore_snapshot(book, top_level)

        oversized_return_name = " " * 256 + "x"
        return_snapshot = dict(valid)
        return_snapshot["return_points"] = {
            oversized_return_name: valid["current_target"]
        }
        with self.assertRaisesRegex(ValueError, "exceeds 256"):
            BookReader.restore_snapshot(book, return_snapshot)

        fallback_reader = BookReader(book)
        fallback_reader.go_to(1)
        fallback_snapshot = fallback_reader.snapshot()
        oversized_fallback_key = "index:" + ("9" * 4091)
        self.assertGreater(len(oversized_fallback_key), 4096)
        fallback_snapshot["fallback_digests"] = {
            oversized_fallback_key: "0" * 64
        }
        with self.assertRaisesRegex(ValueError, "exceeds 4096"):
            BookReader.restore_snapshot(book, fallback_snapshot)

    def test_boundaries_and_invalid_return_points_fail_explicitly(self):
        reader = BookReader(self.make_book())
        with self.assertRaisesRegex(LookupError, "Beginning"):
            reader.previous_block()
        reader.go_to(6)
        with self.assertRaisesRegex(LookupError, "End"):
            reader.next_block()
        with self.assertRaisesRegex(LookupError, "Unknown return point"):
            reader.restore_return_point("missing")
        with self.assertRaises(IndexError):
            reader.go_to(99)

    def test_navigation_fails_closed_after_document_revision_changes(self):
        book = self.make_book()
        reader = BookReader(book)
        reader.go_to(3)
        book.blocks[2].text = "Changed chapter"

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.location()
        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.next_heading()
        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.navigation_availability()
        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.go_to(0)
        self.assertEqual(reader.index, 3)

    def test_live_revision_rejects_rebound_document_subclass_before_attribute_hook(self):
        book = self.make_book()
        reader = BookReader(book)

        class HostileDocument(BookDocument):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name == "blocks":
                    type(self).touched = True
                    raise AssertionError("rejected live document root must remain passive")
                return super().__getattribute__(name)

        replacement = HostileDocument("Replacement")
        reader.document = replacement
        HostileDocument.armed = True

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.location()
        self.assertFalse(HostileDocument.touched)

    def test_live_revision_keeps_blocks_only_identity_for_exact_document_rebind(self):
        book = self.make_book()
        reader = BookReader(book)

        replacement = BookDocument.from_dict(book.as_dict())
        replacement.title = "Equivalent exact document root"
        replacement.warnings.append("Metadata remains outside reader revision identity")
        reader.document = replacement

        self.assertEqual(reader.location().block_id, "part-1")
    def test_live_revision_rejects_blocks_list_subclass_before_iteration_hook(self):
        book = self.make_book()
        reader = BookReader(book)

        class HostileBlocks(list):
            armed = False
            touched = False

            def __iter__(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("live blocks iteration hook must not execute")
                return super().__iter__()

        hostile = HostileBlocks(book.blocks)
        book.blocks = hostile
        HostileBlocks.armed = True

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.location()
        self.assertFalse(HostileBlocks.touched)

    def test_live_revision_rejects_block_subclass_before_method_hook(self):
        book = self.make_book()
        reader = BookReader(book)

        class HostileHeading(Heading):
            armed = False
            touched = False

            def as_dict(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("live block method hook must not execute")
                return super().as_dict()

        hostile = HostileHeading(text="Replacement", level=1, block_id="part-1")
        book.blocks[0] = hostile
        HostileHeading.armed = True

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.location()
        self.assertFalse(HostileHeading.touched)

    def test_live_revision_digest_remains_blocks_only(self):
        book = self.make_book()
        reader = BookReader(book)

        book.title = "Retitled without changing reading semantics"
        book.warnings.append("New import note")

        self.assertEqual(reader.location().block_id, "part-1")

    def test_detached_metadata_rejects_active_text_before_hooks(self):
        reader = BookReader(
            BookDocument(
                "Reader",
                author="Author",
                language="en",
                blocks=[Heading(text="Part", level=1)],
            )
        )

        class ActiveText(str):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("active metadata length hook must not execute")

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("active metadata strip hook must not execute")

        reader._indexed_document.title = ActiveText("forged")

        with self.assertRaisesRegex(TypeError, "indexed Book reading metadata is invalid"):
            reader.document_title_author_snapshot()
        with self.assertRaisesRegex(TypeError, "indexed Book reading metadata is invalid"):
            reader.block_reading_snapshot(0)

        self.assertFalse(ActiveText.touched)

    def test_detached_metadata_rejects_indexed_document_subclass_before_hooks(self):
        reader = BookReader(self.make_book())

        class HostileDocument(BookDocument):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {"title", "author", "language"}:
                    type(self).touched = True
                    raise AssertionError("indexed metadata root hook must not execute")
                return super().__getattribute__(name)

        hostile = HostileDocument.from_dict(reader._indexed_document.as_dict())
        reader._indexed_document = hostile
        HostileDocument.armed = True

        with self.assertRaisesRegex(TypeError, "indexed BookDocument metadata root is invalid"):
            reader.document_language_snapshot()

        self.assertFalse(HostileDocument.touched)

    def test_detached_metadata_snapshots_preserve_canonical_values(self):
        reader = BookReader(
            BookDocument(
                "Reader title",
                author="Reader author",
                language="uk",
                blocks=[Heading(text="Part", level=1)],
            )
        )

        self.assertEqual(reader.document_title_author_snapshot(), ("Reader title", "Reader author"))
        self.assertEqual(reader.document_language_snapshot(), "uk")
        block, title, author, language = reader.block_reading_snapshot(0)
        self.assertIs(type(block), Heading)
        self.assertEqual((title, author, language), ("Reader title", "Reader author", "uk"))

    def test_navigation_availability_rechecks_revision_after_semantic_scan(self):
        book = self.make_book()
        reader = BookReader(book)
        reader.go_to(3)
        before_index = reader.index

        class MutatingIndexedBlocks(list):
            def __init__(self, values):
                super().__init__(values)
                self.mutated = False

            def __getitem__(self, index):
                value = super().__getitem__(index)
                if isinstance(index, int) and not self.mutated:
                    self.mutated = True
                    book.blocks[0].text = "Concurrent heading"
                return value

        reader._indexed_document.blocks = MutatingIndexedBlocks(
            reader._indexed_document.blocks
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "changed after BookReader creation",
        ):
            reader.navigation_availability()

        self.assertEqual(reader.index, before_index)

    def test_no_match_semantic_scan_rechecks_revision_before_boundary_error(self):
        book = self.make_book()
        reader = BookReader(book)
        reader.go_to(3)
        before_index = reader.index

        class MutatingIndexedBlocks(list):
            def __init__(self, values):
                super().__init__(values)
                self.mutated = False

            def __getitem__(self, index):
                value = super().__getitem__(index)
                if isinstance(index, int) and not self.mutated:
                    self.mutated = True
                    book.blocks[0].text = "Concurrent heading"
                return value

        reader._indexed_document.blocks = MutatingIndexedBlocks(
            reader._indexed_document.blocks
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "changed after BookReader creation",
        ):
            reader.previous_game()

        self.assertEqual(reader.index, before_index)

    def test_snapshot_rechecks_revision_after_return_point_traversal(self):
        book = self.make_book()
        reader = BookReader(book)
        reader.go_to(3)
        reader.save_return_point("analysis")

        class MutatingReturnPoints(dict):
            def items(self):
                mutated = False
                for item in super().items():
                    if not mutated:
                        mutated = True
                        book.blocks[0].text = "Concurrent heading"
                    yield item

        reader._return_points = MutatingReturnPoints(reader._return_points)

        with self.assertRaisesRegex(
            RuntimeError,
            "changed after BookReader creation",
        ):
            reader.snapshot()

    def test_go_to_rolls_back_cursor_if_revision_changes_between_checks(self):
        book = self.make_book()
        reader = BookReader(book)
        reader.go_to(3)
        before_index = reader.index
        original_check = reader._require_indexed_revision
        checks = 0

        def mutate_after_initial_check():
            nonlocal checks
            checks += 1
            original_check()
            if checks == 1:
                book.blocks[2].text = "Concurrent chapter"

        reader._require_indexed_revision = mutate_after_initial_check

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.go_to(6)

        self.assertEqual(reader.index, before_index)

    def test_save_return_point_rolls_back_new_name_on_revision_drift(self):
        book = self.make_book()
        reader = BookReader(book)
        reader.go_to(3)
        original_text = book.blocks[2].text
        original_check = reader._require_indexed_revision
        checks = 0

        def mutate_after_target_validation():
            nonlocal checks
            checks += 1
            original_check()
            if checks == 1:
                # Mutate immediately after the operation's preflight. The
                # final barrier, not a redundant intermediate whole-book hash,
                # must reject publication and preserve rollback semantics.
                book.blocks[2].text = "Concurrent chapter"

        reader._require_indexed_revision = mutate_after_target_validation

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.save_return_point("race")

        book.blocks[2].text = original_text
        with self.assertRaisesRegex(LookupError, "Unknown return point"):
            reader.restore_return_point("race")
        self.assertEqual(reader.index, 3)

    def test_save_return_point_restores_previous_target_on_revision_drift(self):
        book = self.make_book()
        reader = BookReader(book)
        reader.go_to(3)
        reader.save_return_point("analysis")
        reader.go_to(6)
        original_text = book.blocks[2].text
        original_check = reader._require_indexed_revision
        checks = 0

        def mutate_after_target_validation():
            nonlocal checks
            checks += 1
            original_check()
            if checks == 1:
                # Mutate immediately after the operation's preflight. The
                # final barrier, not a redundant intermediate whole-book hash,
                # must reject publication and preserve rollback semantics.
                book.blocks[2].text = "Concurrent chapter"

        reader._require_indexed_revision = mutate_after_target_validation

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.save_return_point("analysis")

        book.blocks[2].text = original_text
        restored = reader.restore_return_point("analysis")
        self.assertEqual(restored.index, 3)
        self.assertEqual(restored.block_id, "diagram")

    def test_location_stays_on_one_indexed_revision_if_live_document_changes_after_validation(self):
        book = self.make_book()
        reader = BookReader(book)
        reader.go_to(3)
        original_check = reader._require_indexed_revision
        mutated = False

        def mutate_after_check():
            nonlocal mutated
            original_check()
            if not mutated:
                book.blocks[2].text = "Concurrent chapter"
                mutated = True

        reader._require_indexed_revision = mutate_after_check
        location = reader.location()
        self.assertEqual(location.block_id, "diagram")
        self.assertEqual(location.heading_path, ("Part I", "Chapter"))
        self.assertEqual(location.position_fen, WHITE_FEN)

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.location()

    def test_document_snapshot_is_detached_and_revision_bound(self):
        book = self.make_book()
        reader = BookReader(book)

        snapshot = reader.document_snapshot()
        self.assertIsNot(snapshot, book)
        self.assertIsNot(snapshot.blocks, book.blocks)
        snapshot.blocks[1].text = "Caller mutation"
        self.assertEqual(reader.block_snapshot(1).text, "Intro")

        book.blocks[1].text = "Live mutation"
        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.document_snapshot()
    def test_block_snapshot_is_detached_and_fails_closed_after_live_revision_changes(self):
        book = self.make_book()
        reader = BookReader(book)
        block = reader.block_snapshot(1)
        self.assertEqual(block.text, "Intro")
        block.text = "Caller mutation"
        self.assertEqual(reader.block_snapshot(1).text, "Intro")

        book.blocks[1].text = "Live mutation"
        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.block_snapshot(1)

    def test_navigation_fails_closed_if_live_document_becomes_invalid(self):
        book = self.make_book()
        reader = BookReader(book)
        reader.go_to(3)
        before_index = reader.index

        book.blocks[2].text = ""
        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.location()
        self.assertEqual(reader.index, before_index)

    def test_navigation_fails_closed_if_live_blocks_contain_invalid_object(self):
        book = self.make_book()
        reader = BookReader(book)
        before_index = reader.index

        book.blocks.append(object())
        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.navigation_availability()
        self.assertEqual(reader.index, before_index)

    def test_navigation_fails_closed_if_document_becomes_empty(self):
        book = self.make_book()
        reader = BookReader(book)
        book.blocks.clear()
        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            reader.location()

    def test_restore_snapshot_rechecks_revision_after_target_navigation(self):
        book = self.make_book()
        source = BookReader(book)
        source.go_to(3)
        source.save_return_point("analysis")
        snapshot = source.snapshot()
        original_go_to_target = BookReader._go_to_target

        def mutate_after_target_navigation(reader, key):
            location = original_go_to_target(reader, key)
            book.blocks[0].text = "Concurrent heading"
            return location

        BookReader._go_to_target = mutate_after_target_navigation
        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "changed after BookReader creation",
            ):
                BookReader.restore_snapshot(book, snapshot)
        finally:
            BookReader._go_to_target = original_go_to_target

    def test_restore_empty_snapshot_rechecks_revision_before_publication(self):
        book = BookDocument("Empty")
        snapshot = BookReader(book).snapshot()
        original_init = BookReader.__init__

        def mutate_after_reader_indexing(reader, document):
            original_init(reader, document)
            document.blocks.append(Paragraph(text="Concurrent content"))

        BookReader.__init__ = mutate_after_reader_indexing
        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "changed after BookReader creation",
            ):
                BookReader.restore_snapshot(book, snapshot)
        finally:
            BookReader.__init__ = original_init

    def test_empty_book_is_explicit_not_silent(self):
        reader = BookReader(BookDocument("Empty"))
        with self.assertRaisesRegex(LookupError, "no readable blocks"):
            reader.location()


    def test_provisional_return_point_commits_on_success(self):
        reader = BookReader(self.make_book())
        reader.go_to(3)

        with reader.provisional_return_point("handoff") as location:
            self.assertEqual(location.index, 3)

        reader.go_to(6)
        self.assertEqual(reader.restore_return_point("handoff").index, 3)

    def test_provisional_return_point_removes_new_binding_on_failure(self):
        reader = BookReader(self.make_book())
        reader.go_to(3)

        with self.assertRaisesRegex(RuntimeError, "handoff failed"):
            with reader.provisional_return_point("handoff"):
                raise RuntimeError("handoff failed")

        with self.assertRaisesRegex(LookupError, "Unknown return point: handoff"):
            reader.restore_return_point("handoff")

    def test_provisional_return_point_restores_previous_binding_on_failure(self):
        reader = BookReader(self.make_book())
        reader.go_to(3)
        reader.save_return_point("handoff")
        reader.go_to(5)

        with self.assertRaisesRegex(RuntimeError, "handoff failed"):
            with reader.provisional_return_point("handoff"):
                raise RuntimeError("handoff failed")

        reader.go_to(6)
        restored = reader.restore_return_point("handoff")
        self.assertEqual(restored.index, 3)
        self.assertEqual(restored.block_id, "diagram")


if __name__ == "__main__":
    unittest.main()
