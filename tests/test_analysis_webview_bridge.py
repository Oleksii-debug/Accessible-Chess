from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_analysis_context_is_resolved_before_document_actions():
    assert "resolveBinding(chord,'analysis','analysis')" in HTML


def test_unhandled_central_actions_dispatch_to_release_api():
    assert "typeof a.dispatch_action==='function'" in HTML
    assert "apiAction('dispatch_action',id)" in HTML


def test_analysis_refresh_updates_only_engine_section_without_live_announcement():
    assert "async function refreshAnalysis()" in HTML
    assert "setText('engine-status',s.engineStatus)" in HTML
    refresh = HTML.split("async function refreshAnalysis()", 1)[1].split("function applyUiLanguage", 1)[0]
    assert "announce(" not in refresh
    assert "renderBoard(" not in refresh
    assert "setInterval(refreshAnalysis,750)" in HTML


def test_semantic_stockfish_section_remains_non_live_and_locked_heading():
    assert '<h2 id="h-engine">Аналіз Stockfish</h2>' in HTML
    assert 'id="engine-status" class="block" aria-live="off"' in HTML


def test_help_exposes_active_analysis_shortcuts_from_registry():
    for action_id in (
        "analysis.pv1", "analysis.pv2", "analysis.pv3", "analysis.pv4", "analysis.pv5",
        "board.evaluation", "board.best_move", "board.play_best",
    ):
        assert f"line('{action_id}')" in HTML
