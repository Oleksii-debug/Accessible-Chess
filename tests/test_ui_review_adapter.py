from acs.history import ReviewHistory
from acs.ui_review_adapter import ReviewPresentationAdapter


START = "start-fen"
FEN1 = "fen-after-e4"
FEN2 = "fen-after-e5"
FEN3 = "fen-after-nf3"


def _history() -> ReviewHistory:
    history = ReviewHistory(START)
    history.append(FEN1, san="e4", side="w", last_move="e4")
    history.append(FEN2, san="e5", side="b", last_move="e5")
    history.append(FEN3, san="Nf3", side="w", last_move="Nf3")
    return history


def test_adapter_moves_only_review_cursor_and_returns_fen_projection():
    history = _history()
    live_game_guard = {"fen": FEN3, "undo_depth": 3, "redo_depth": 0}
    adapter = ReviewPresentationAdapter(history, language="en")
    previous = adapter.previous()
    assert previous.ok
    assert previous.view.fen == FEN2
    assert previous.view.ply == 2
    assert not previous.view.at_end
    assert live_game_guard == {"fen": FEN3, "undo_depth": 3, "redo_depth": 0}
    end = adapter.jump("end")
    assert end.ok
    assert end.view.fen == FEN3
    assert end.view.at_end
    assert live_game_guard["undo_depth"] == 3


def test_adapter_supports_locked_jump_forms_and_stable_node_ids():
    adapter = ReviewPresentationAdapter(_history(), language="uk")
    start = adapter.jump("start")
    assert start.ok and start.view.ply == 0 and start.view.node_id == 0
    white_two = adapter.jump("2w")
    assert white_two.ok
    assert white_two.view.ply == 3
    assert white_two.view.node_id == 3
    assert white_two.view.last_move == "Nf3"
    black_one = adapter.jump("1...")
    assert black_one.ok
    assert black_one.view.ply == 2
    assert black_one.view.node_id == 2


def test_adapter_preserves_cursor_on_invalid_jump_and_reports_accessibly():
    history = _history()
    adapter = ReviewPresentationAdapter(history, language="uk")
    before = adapter.current()
    result = adapter.jump("99")
    assert not result.ok
    assert result.view.node_id == before.node_id
    assert result.view.fen == before.fen
    assert "Не вдалося" in result.announcement


def test_adapter_reports_start_and_end_boundaries_without_mutation():
    history = _history()
    adapter = ReviewPresentationAdapter(history, language="en")
    at_end = adapter.next()
    assert not at_end.ok
    assert at_end.view.at_end
    assert at_end.announcement == "Already at the end of history."
    adapter.jump("start")
    at_start = adapter.previous()
    assert not at_start.ok
    assert at_start.view.at_start
    assert at_start.announcement == "Already at the initial position."


def test_reviewhistory_tree_exchange_roundtrip_preserves_branch_identity():
    history = _history()
    history.jump("1w")
    variation = history.append("fen-after-c5", san="c5", side="b", last_move="c5")
    tree = history.export_tree()
    restored = ReviewHistory.from_tree(tree)
    assert restored.cursor_node_id == variation.node_id
    assert restored.export_tree() == tree
    assert [snapshot.san for snapshot in restored.active_line()] == [None, "e4", "c5"]
