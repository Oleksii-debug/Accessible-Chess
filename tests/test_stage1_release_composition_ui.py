from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.release_app import create_release_api
from acs.sound_events import SoundEvent
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI, complete_user_flow_diagnostic


class _FakeLine:
    def __init__(self, multipv: int) -> None:
        self.multipv = multipv
        self.depth = 14
        self.score_kind = "cp"
        self.score_value = multipv * 12
        self.pv = ("e2e4", "e7e5")


class _FakeEngine:
    def __init__(self) -> None:
        self.closed = False

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        return tuple(_FakeLine(i) for i in range(1, multipv + 1))

    def best_move(self, fen: str, skill_level: int = 10, movetime_ms: int = 500):
        return "e2e4"

    def close(self) -> None:
        self.closed = True


class _FakeRuntime:
    def __init__(self, config) -> None:
        self.config = config
        self.engine = _FakeEngine()
        self.closed = False

    def provider(self):
        return self.engine

    def close(self) -> None:
        self.closed = True
        self.engine.close()


class _Playback:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[SoundEvent, int]] = []
        self.fail = fail

    def play(self, event: SoundEvent, *, volume: int) -> None:
        self.calls.append((event, volume))
        if self.fail:
            raise RuntimeError(r"C:\private\audio-device\driver failed")


class Stage1ReleaseCompositionUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.bootstrap = (self.root / "web" / "stage1_release_bootstrap.js").read_text(encoding="utf-8")
        self.html = (self.root / "web" / "index.html").read_text(encoding="utf-8")

    def make_composed(self, root: str, playback: _Playback | None = None):
        return create_release_api(
            application_dir=root,
            runtime_factory=_FakeRuntime,
            sound_playback=playback or _Playback(),
            settings_path=Path(root) / "settings.json",
        )

    def test_packaged_composition_uses_one_stage1_api_for_engine_sound_and_user_flow(self) -> None:
        playback = _Playback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            self.assertIsInstance(api, Stage1ReleaseAccessibleChessAPI)
            try:
                flow = complete_user_flow_diagnostic(api)
                self.assertTrue(flow["ok"], flow)
                self.assertEqual(flow["boardCells"], 64)
                self.assertIn((SoundEvent.START, 80), playback.calls)
                self.assertIn((SoundEvent.MOVE, 80), playback.calls)
                self.assertIn((SoundEvent.ILLEGAL, 80), playback.calls)
                analysis = api.toggle_engine()
                self.assertTrue(analysis["ok"])
                state = api.get_state()
                self.assertTrue(state["engineEnabled"])
                self.assertEqual(state["analysis"]["multipv"], 5)
            finally:
                api.close_analysis()
                runtime.close()
            self.assertTrue(runtime.closed)

    def test_sound_settings_persist_drive_runtime_and_preview_is_real(self) -> None:
        playback = _Playback()
        with tempfile.TemporaryDirectory() as td:
            settings_path = Path(td) / "settings.json"
            api, runtime = create_release_api(
                application_dir=td,
                runtime_factory=_FakeRuntime,
                sound_playback=playback,
                settings_path=settings_path,
            )
            try:
                self.assertTrue(api.set_sound_volume(35)["ok"])
                preview = api.preview_sound("capture")
                self.assertTrue(preview["ok"], preview)
                self.assertEqual(playback.calls[-1], (SoundEvent.CAPTURE, 35))
                before = len(playback.calls)
                self.assertTrue(api.set_sound_enabled(False)["ok"])
                disabled = api.preview_sound("move")
                self.assertFalse(disabled["ok"])
                self.assertEqual(len(playback.calls), before)
            finally:
                api.close_analysis()
                runtime.close()

            api2, runtime2 = create_release_api(
                application_dir=td,
                runtime_factory=_FakeRuntime,
                sound_playback=_Playback(),
                settings_path=settings_path,
            )
            try:
                restored = api2.get_sound_settings()
                self.assertFalse(restored["enabled"])
                self.assertEqual(restored["volume"], 35)
            finally:
                api2.close_analysis()
                runtime2.close()

    def test_sound_failure_is_concise_and_never_leaks_exception_or_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, _Playback(fail=True))
            try:
                result = api.preview_sound("move")
                self.assertFalse(result["ok"])
                message = result["message"]
                self.assertNotIn("RuntimeError", message)
                self.assertNotIn("C:\\private", message)
                self.assertLessEqual(len(message), 80)
            finally:
                api.close_analysis()
                runtime.close()

    def test_webview_bootstrap_preserves_initial_move_edit_and_base_enter_dispatch(self) -> None:
        text = self.bootstrap
        self.assertIn("function installMoveEntryIdentity()", text)
        self.assertIn("input.addEventListener('focusin', rememberMoveInputFocus)", text)
        self.assertIn("stage1MoveIdentityReady", text)
        self.assertNotIn("document.createElement('form')", text)
        self.assertNotIn("form.appendChild(input)", text)
        self.assertNotIn("row.replaceWith", text)
        self.assertIn("el('move-submit').addEventListener('click',submitMove)", self.html)
        self.assertIn("el('move-input').addEventListener('keydown'", self.html)
        self.assertNotIn("document.addEventListener('keydown'", text)
        self.assertNotIn("window.addEventListener('keydown'", text)

    def test_move_edit_runtime_exposure_contract_targets_webview_accessibility_mechanism(self) -> None:
        text = self.bootstrap
        self.assertIn("function moveEntryExposureState()", text)
        self.assertIn("input.isConnected", text)
        self.assertIn("input.type === 'text'", text)
        self.assertIn("input.getAttribute('role') === 'textbox'", text)
        self.assertIn("input.getAttribute('aria-label') === moveEntryLabels().input", text)
        self.assertIn("input.tabIndex >= 0", text)
        self.assertIn("input.closest('[hidden],[inert],[aria-hidden=\"true\"]')", text)
        self.assertIn("window.getComputedStyle(input)", text)
        self.assertIn("style.display !== 'none'", text)
        self.assertIn("style.visibility !== 'hidden'", text)
        self.assertIn("document.body.dataset.stage1MoveAccessibilityExposed", text)
        self.assertIn("window.__accessibleChessMoveEntryExposureState = moveEntryExposureState", text)
        semantics = text[text.index("function stabilizeMoveEntryUiaSemantics()"):text.index("function stableBoardAccessibleName")]
        self.assertIn("input.setAttribute('role', 'textbox')", semantics)
        self.assertIn("input.setAttribute('aria-label', labels.input)", semantics)
        self.assertIn("input.setAttribute('tabindex', '0')", semantics)
        self.assertIn("publishMoveEntryExposureState()", semantics)
        self.assertNotIn("aria-hidden", self.html.split('<input id=\"move-input\"', 1)[1].split('>', 1)[0])

    def test_board_origin_move_preserves_board_focus_without_changing_input_semantics(self) -> None:
        text = self.bootstrap
        self.assertIn("const focusState = window.__accessibleChessStage1FocusState", text)
        self.assertIn("function rememberBoardFocus(cell)", text)
        self.assertIn("function rememberMoveInputFocus()", text)
        self.assertIn("function installMoveFocusPolicy()", text)
        self.assertIn("const active = document.activeElement", text)
        self.assertIn("active.closest('[role=\"gridcell\"]')", text)
        self.assertIn("const activeBoardSquare = activeCell && grid && grid.contains(activeCell)", text)
        self.assertIn("focusState.context === 'board' ? focusState.boardSquare : ''", text)
        self.assertIn("const result = await baseSubmit.apply(this, args)", text)
        self.assertIn("if (boardSquare) settleBoardFocusAfterInvoke(boardSquare)", text)
        self.assertIn("function restoreBoardSquare(square, generation)", text)
        self.assertIn("byId('sq-' + square)", text)
        self.assertIn("target.focus({preventScroll: true})", text)
        self.assertIn("setTimeout(() => restoreBoardSquare(square, generation), 0)", text)
        self.assertIn("setTimeout(() => restoreBoardSquare(square, generation), 50)", text)
        self.assertIn("rememberBoardFocus(target)", text)
        self.assertIn("input.addEventListener('focusin', rememberMoveInputFocus)", text)
        self.assertIn("stage1MoveFocusPolicyReady", text)
        self.assertLess(text.index("installMoveFocusPolicy();"), text.index("installMoveEntryIdentity();"))
        self.assertNotIn("document.addEventListener('keydown'", text)
        self.assertNotIn("window.addEventListener('keydown'", text)

    def test_board_focus_survives_state_driven_grid_replacement_without_global_key_hijack(self) -> None:
        text = self.bootstrap
        self.assertIn("function installBoardFocusContinuity()", text)
        self.assertIn("function stabilizeBoardUiaSemantics", text)
        self.assertIn("grid.addEventListener('focusin'", text)
        self.assertIn("rememberBoardFocus(cell)", text)
        self.assertIn("new MutationObserver(records =>", text)
        self.assertIn("record.removedNodes", text)
        self.assertIn("focusState.boardNode", text)
        self.assertIn("focusState.boardSquare", text)
        self.assertIn("byId('sq-' + focusState.boardSquare)", text)
        self.assertIn("target.focus({preventScroll: true})", text)
        self.assertIn("rememberBoardFocus(target)", text)
        self.assertIn("stage1BoardFocusContinuityReady", text)
        self.assertIn("stage1BoardUiaSemanticsReady", text)
        self.assertIn("installBoardFocusContinuity();", text)
        self.assertNotIn("document.addEventListener('keydown'", text)
        self.assertNotIn("window.addEventListener('keydown'", text)

    def test_webview_bootstrap_exposes_accessible_sound_controls_without_new_live_region(self) -> None:
        text = self.bootstrap
        for element_id in (
            "sound-settings", "sound-enabled", "sound-volume",
            "sound-preview-event", "sound-preview", "sound-settings-status",
        ):
            self.assertIn(element_id, text)
        self.assertIn("a.get_sound_settings", text)
        self.assertIn("a.set_sound_enabled", text)
        self.assertIn("a.set_sound_volume", text)
        self.assertIn("a.preview_sound", text)
        self.assertIn("status.setAttribute('aria-live', 'off')", text)
        self.assertNotIn("role', 'status", text)
        self.assertNotIn("role=\"status\"", text)

    def test_startup_ready_contract_keeps_accessibility_subtree_available_and_launcher_consumes_bootstrap(self) -> None:
        self.assertNotIn("main.setAttribute('aria-busy'", self.bootstrap)
        self.assertIn("publishMoveEntryExposureState();", self.bootstrap)
        self.assertIn("requestAnimationFrame(() => publishMoveEntryExposureState())", self.bootstrap)
        self.assertIn("document.body.dataset.stage1AppReady = 'true'", self.bootstrap)
        ready = self.bootstrap[self.bootstrap.index("async function markReady()"):self.bootstrap.index("installMoveFocusPolicy();")]
        self.assertLess(ready.index("publishMoveEntryExposureState();"), ready.index("stage1AppReady = 'true'"))
        source = (self.root / "acs" / "stage1_release_ui.py").read_text(encoding="utf-8")
        self.assertIn('"stage1_release_bootstrap.js"', source)
        self.assertIn("window.events.loaded += install_release_web_contract", source)
        self.assertIn("from .release_app import create_release_api", source)

    def test_release_composition_no_longer_has_a_second_ui_api(self) -> None:
        source = (self.root / "acs" / "release_app.py").read_text(encoding="utf-8")
        self.assertNotIn("class ReleaseAccessibleChessAPI", source)
        self.assertIn("ReleaseAccessibleChessAPI = Stage1ReleaseAccessibleChessAPI", source)
        self.assertIn("settings=lambda: SoundRuntimeSettings.from_mapping(settings.data)", source)
        launcher = (self.root / "run_accessible_chess.py").read_text(encoding="utf-8")
        self.assertIn("from acs.stage1_release_ui import main", launcher)


if __name__ == "__main__":
    unittest.main()
