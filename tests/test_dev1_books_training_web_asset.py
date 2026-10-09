from __future__ import annotations

from pathlib import Path
import unittest


ASSET = Path("web/full_product_books_training.js")


class BooksTrainingWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = ASSET.read_text(encoding="utf-8")

    def test_native_bookmark_and_training_answer_controls_preserve_editing_semantics(self) -> None:
        text = self.text
        self.assertIn('input.id = "book-bookmark-name"', text)
        self.assertIn('input.id = "training-answer"', text)
        self.assertIn('input.type = "text"', text)
        self.assertIn('form.addEventListener("submit"', text)
        for chord in ("Ctrl+A", "Ctrl+C", "Ctrl+X", "Ctrl+V", "Meta+A", "Meta+C"):
            self.assertNotIn(chord, text)
        self.assertNotIn("clipboardData", text)
        self.assertNotIn("navigator.clipboard", text)

    def test_no_global_keyboard_interception_or_html_injection(self) -> None:
        text = self.text
        self.assertNotIn('document.addEventListener("keydown"', text)
        self.assertNotIn('window.addEventListener("keydown"', text)
        self.assertNotIn('global.addEventListener("keydown"', text)
        for token in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(token, text)

    def test_book_list_rendering_requires_canonical_role_metadata(self) -> None:
        text = self.text
        self.assertIn(
            'const roles = ["heading", "paragraph", "img", "group", "tree", "note", "list"]',
            text,
        )
        self.assertIn('if (block.role === "list")', text)
        self.assertIn('throw new TypeError("Book list block requires list metadata")', text)
        self.assertIn('throw new TypeError("Book list items are invalid")', text)
        self.assertIn('throw new TypeError("Book list ordered flag is invalid")', text)
        self.assertIn('throw new TypeError("Book list start is invalid")', text)
        self.assertIn('throw new TypeError("Unordered Book list cannot define a start")', text)
        self.assertIn('throw new TypeError("Non-list Book block contains list metadata")', text)

    def test_book_lists_render_as_native_selectable_list_dom(self) -> None:
        text = self.text
        self.assertIn('content = node(block.list.ordered ? "ol" : "ul")', text)
        self.assertIn('content.setAttribute("start", String(block.list.start))', text)
        self.assertIn('content.appendChild(node("li", text))', text)
        self.assertIn('element.textContent = String(text)', text)
        self.assertNotIn('content.setAttribute("role", "list")', text)
        self.assertNotIn('setAttribute("role", "listitem")', text)

    def test_passive_messages_are_not_background_live_regions(self) -> None:
        text = self.text
        self.assertIn('warning.setAttribute("aria-live", "off")', text)
        self.assertIn('message.setAttribute("aria-live", "off")', text)
        self.assertNotIn('aria-live", "polite"', text)
        self.assertNotIn('aria-live", "assertive"', text)

    def test_reset_uses_native_dialog_and_restores_opener_on_cancel(self) -> None:
        text = self.text
        self.assertIn('const dialog = node("dialog")', text)
        self.assertIn('dialog.setAttribute("aria-labelledby"', text)
        self.assertIn('dialog.showModal()', text)
        self.assertIn('opener.focus({ preventScroll: true })', text)
        self.assertIn('{ confirmed: true }', text)
        self.assertIn('if (result && result.kind === "error")', text)
        self.assertIn('if (dialog.open) dialog.close()', text)
        self.assertIn('if (resetPending) return', text)
        self.assertGreaterEqual(
            text.count("const activeFlight = inFlightRoots.get(root)"),
            2,
        )

    def test_wrong_training_answer_is_preserved_locally_but_accepted_answer_clears(self) -> None:
        text = self.text
        self.assertIn('let priorAnswer = ""', text)
        self.assertIn('if (!payload.clear_answer && priorAnswer)', text)
        self.assertIn('next.value = priorAnswer', text)
        self.assertNotIn("accepted_moves", text)
        self.assertNotIn("start_fen", text)

    def test_transport_throw_and_rejection_are_caught_with_one_flight_actions(self) -> None:
        text = self.text
        self.assertIn("const inFlightRoots = new WeakMap()", text)
        self.assertIn("const renderEpochs = new WeakMap()", text)
        self.assertIn("const activeFlight = inFlightRoots.get(root)", text)
        self.assertIn("if (activeFlight && activeFlight.epoch === startedAtEpoch) return", text)
        self.assertIn("const flight = { epoch: startedAtEpoch }", text)
        self.assertIn("inFlightRoots.set(root, flight)", text)
        self.assertIn("if (inFlightRoots.get(root) !== flight) return", text)
        self.assertIn('root.setAttribute("aria-busy", "true")', text)
        self.assertIn('root.removeAttribute("aria-busy")', text)
        self.assertIn("renderEpoch(root) === startedAtEpoch", text)
        self.assertGreaterEqual(text.count("markRendered(root)"), 2)
        self.assertIn("try {", text)
        self.assertIn("result = invoke(command, payload || {})", text)
        self.assertIn("catch (_)", text)
        self.assertIn("Promise.resolve(result)", text)
        self.assertIn(".catch(fail)", text)
        self.assertIn("if (fallbackMessage) announce(fallbackMessage)", text)
        self.assertEqual(text.count("inFlightRoots.delete(root)"), 2)
        self.assertNotIn("new WeakSet()", text)
        self.assertNotIn("Promise.resolve(invoke(", text)
        self.assertNotIn("error.message", text)
        self.assertNotIn("String(error)", text)

    def test_book_and_training_surfaces_project_native_main_and_language(self) -> None:
        text = self.text
        self.assertEqual(text.count('const main = node("main")'), 2)
        self.assertEqual(
            text.count('main.setAttribute("lang", snapshot.document.lang)'),
            2,
        )
        self.assertIn('requireDocumentSpec(snapshot, "Book")', text)
        self.assertIn('requireDocumentSpec(snapshot, "Training")', text)
        self.assertIn('documentSpec.landmark !== "main"', text)
        self.assertIn('documentSpec.lang !== "uk" && documentSpec.lang !== "en"', text)
        self.assertNotIn('const main = node("section")', text)
        self.assertNotIn(');\\n    main.setAttribute("lang"', text)

    def test_malformed_host_events_fail_closed_before_surface_mutation(self) -> None:
        text = self.text
        self.assertIn("function requireHostEvent(result, allowedKinds, surface)", text)
        self.assertIn('throw new TypeError(surface + " host result must be an object")', text)
        self.assertIn('throw new TypeError(surface + " host result kind is invalid")', text)
        self.assertIn('throw new TypeError(surface + " host result payload must be an object")', text)
        self.assertIn('throw new TypeError(surface + " render result requires a snapshot")', text)
        self.assertIn(
            'requireHostEvent(result, ["render", "error", "delegated"], "Book")',
            text,
        )
        self.assertIn(
            'requireHostEvent(result, ["render", "error"], "Training")',
            text,
        )
        self.assertIn('requireSnapshotRecord(snapshot, "block", "Book")', text)
        self.assertIn('requireSnapshotRecord(snapshot, "bookmark", "Book")', text)
        self.assertIn('requireSnapshotRecord(snapshot, "document", surface)', text)
        self.assertIn("function requireActions(actions, commands, surface)", text)
        self.assertIn('throw new TypeError(surface + " snapshot actions are incomplete")', text)
        self.assertIn('throw new TypeError(surface + " snapshot action is invalid")', text)
        self.assertIn('throw new TypeError(surface + " snapshot action command/order is invalid")', text)
        self.assertIn('throw new TypeError(surface + " snapshot action label is invalid")', text)
        self.assertIn('throw new TypeError(surface + " snapshot action enabled flag is invalid")', text)
        self.assertIn('throw new TypeError("Book snapshot block DOM id is not canonical")', text)
        self.assertIn('requireSnapshotRecord(snapshot, "progress", "Training")', text)
        self.assertIn('requireSnapshotRecord(snapshot, "answer", "Training")', text)
        self.assertIn('requireSnapshotRecord(snapshot, "reset_dialog", "Training")', text)
        self.assertIn('"book.return_from_board"', text)
        self.assertIn('"training.reset.request"', text)
        self.assertIn('throw new TypeError("Book render focus target is invalid")', text)
        self.assertIn(
            'payload.action !== "book.open_position" && payload.action !== "book.open_game"',
            text,
        )
        self.assertIn('throw new TypeError("Book delegated action is invalid")', text)
        self.assertIn('throw new TypeError("Book starter material id is duplicated")', text)
        self.assertIn('throw new TypeError("Book open-position action disagrees with block position state")', text)
        self.assertIn('throw new TypeError("Book open-game action disagrees with block game state")', text)
        self.assertIn('throw new TypeError("Book board-active state is invalid")', text)
        self.assertIn('throw new TypeError("Book open-position action disagrees with board state")', text)
        self.assertIn('throw new TypeError("Book open-game action disagrees with board state")', text)
        self.assertIn('throw new TypeError("Book return action disagrees with board state")', text)
        self.assertIn('"book.open_game"', text)
        self.assertIn('throw new TypeError("Training progress counter is invalid")', text)
        self.assertIn('throw new TypeError("Training step counters are inconsistent")', text)
        self.assertIn('throw new TypeError("Training completion state is inconsistent")', text)
        self.assertIn('throw new TypeError("Training render focus target is invalid")', text)
        self.assertIn('throw new TypeError("Training solution payload is invalid")', text)
        self.assertIn('button.id = trainingActionFocusTarget(action.command)', text)
        self.assertIn('solutionSection.id = "training-solution"', text)
        self.assertIn('solutionSection.tabIndex = -1', text)
        self.assertIn('solutionSection.setAttribute("aria-labelledby", solutionHeading.id)', text)
        self.assertIn('function requireTrainingSolution(solution)', text)
        self.assertIn('Object.prototype.hasOwnProperty.call(solution, index)', text)
        self.assertIn('solution = requireTrainingSolution(solution)', text)
        self.assertIn('canonicalTrainingFocusTarget(snapshot)', text)
        self.assertIn('allowed.add("training-solution")', text)
        self.assertIn(
            'requireBoundedText(action.label, surface + " snapshot action label", false, 120)',
            text,
        )
        self.assertIn(
            'requireBoundedText(payload.message, "Book error message", false, 1000)',
            text,
        )
        self.assertIn(
            'requireBoundedText(payload.message, "Training error message", false, 1200)',
            text,
        )
        self.assertIn('action.command !== commands[index]', text)
        self.assertIn('block.dom_id !== "book-block-" + String(block.index)', text)
        self.assertIn('catalogue.items.length !== catalogue.booklet_count + 1', text)
        self.assertIn('const roleByKind = {', text)
        self.assertIn('roleByKind[block.kind] !== block.role', text)
        self.assertIn(
            'throw new TypeError("Book snapshot block kind/role is inconsistent")',
            text,
        )
        self.assertIn(
            'block.has_position !== (positionKinds.indexOf(block.kind) >= 0)',
            text,
        )
        self.assertIn(
            'throw new TypeError("Book snapshot position flag disagrees with semantic kind")',
            text,
        )

    def test_browser_rechecks_canonical_snapshot_budgets(self) -> None:
        text = self.text
        self.assertIn("const MAX_BOOKMARK_NAME = 80", text)
        self.assertIn("const MAX_BOOK_BLOCK_VISIBLE_CHARS = 12 * 1024 * 1024", text)
        self.assertIn("const MAX_BOOK_LIST_ITEMS = 65536", text)
        self.assertIn("block.list.items.length > MAX_BOOK_LIST_ITEMS", text)
        self.assertIn("const MAX_BOOK_HEADING_PATH_PARTS = 6", text)
        self.assertIn("const MAX_STARTER_BOOKLETS = 24", text)
        self.assertIn("const MAX_TRAINING_SOLUTION_MOVES = 64", text)
        self.assertIn("function requireBoundedText(value, label, allowEmpty, limit)", text)
        self.assertIn('text.length > limit || text.indexOf("\\x00") >= 0', text)
        self.assertIn('bookmark.max_length !== MAX_BOOKMARK_NAME', text)
        self.assertIn('block.heading_path.length > MAX_BOOK_HEADING_PATH_PARTS', text)
        self.assertIn('listVisibleChars > MAX_BOOK_BLOCK_VISIBLE_CHARS', text)
        self.assertIn('catalogue.booklet_count > MAX_STARTER_BOOKLETS', text)
        self.assertIn('solution.length > MAX_TRAINING_SOLUTION_MOVES', text)
        self.assertIn('move.length > MAX_TRAINING_SOLUTION_TEXT', text)
        self.assertIn(
            'requireBoundedText(payload.announcement, "Book announcement", true, 1000)',
            text,
        )
        self.assertIn(
            'requireBoundedText(payload.announcement, "Training announcement", true, 1200)',
            text,
        )

    def test_starter_material_actions_reuse_the_canonical_book_root(self) -> None:
        text = self.text
        self.assertIn(
            'applyBookEvent(root, result, invoke, announce, fallbackMessage)',
            text,
        )
        self.assertNotIn(
            'applyBookEvent(main.parentNode, result, invoke, announce, fallbackMessage)',
            text,
        )

    def test_book_position_path_has_no_browser_fen_or_direct_board_mutation(self) -> None:
        text = self.text
        self.assertNotIn("position_fen", text)
        self.assertNotIn("start_fen", text)
        self.assertNotIn("board.set_fen", text)
        self.assertNotIn("executeAction", text)


if __name__ == "__main__":
    unittest.main()
