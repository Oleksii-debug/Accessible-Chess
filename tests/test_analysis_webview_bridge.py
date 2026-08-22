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
    assert "setInterval(refreshAnalysis,700)" in HTML


def test_semantic_stockfish_section_remains_non_live_and_locked_heading():
    assert '<h2 id="h-engine">Аналіз Stockfish</h2>' in HTML
    assert 'id="engine-status" class="block" aria-live="off"' in HTML


def test_analysis_shortcuts_are_available_in_help_dialog_not_main_flow():
    assert '<dialog id="help-dialog"' in HTML
    for action_id in ("analysis.pv1", "analysis.pv2", "analysis.pv3", "analysis.pv4", "analysis.pv5"):
        assert f"line('{action_id}')" in HTML


def test_professional_analysis_controls_are_semantic_and_non_live():
    for marker in (
        'id="analysis-multipv"',
        'id="analysis-depth" type="number" min="1" max="40"',
        'id="analysis-lock" type="button" aria-pressed="false"',
        '<ol id="analysis-lines" aria-labelledby="analysis-lines-heading">',
        'id="analysis-explore" type="button"',
        'id="analysis-return" type="button"',
        'id="analysis-insert-move" type="button"',
        'id="analysis-insert-line" type="button"',
        'id="analysis-exploration-status" class="block" aria-live="off"',
    ):
        assert marker in HTML


def test_background_pv_refresh_preserves_nodes_and_never_announces():
    render = HTML.split("function renderAnalysis(s)", 1)[1].split("function render(s)", 1)[0]
    assert "list.textContent=''" not in render
    assert "extra.contains(document.activeElement)" in render
    assert "announce(" not in render


def test_analysis_buttons_call_one_canonical_api_boundary():
    for method in (
        "restart_analysis",
        "toggle_analysis_lock",
        "configure_analysis",
        "select_relative_analysis_pv",
        "explore_analysis_pv",
        "step_analysis_exploration",
        "return_from_analysis",
        "insert_analysis_move",
        "insert_analysis_line",
    ):
        assert f"apiAction('{method}'" in HTML
