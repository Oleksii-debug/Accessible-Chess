from __future__ import annotations

import json
import re
import tempfile
import unittest
from unittest.mock import patch
import wave
from pathlib import Path

from acs.release_app import create_release_api
from acs.sound_events import SoundEvent
from acs.sound_windows import REQUIRED_SOUND_EVENTS
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI, complete_user_flow_diagnostic
from scripts.build_user_sound_pack import NEW_GAME_3D_IMPACT_MS, NEW_GAME_IMPACT_MS


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
        self.stop_calls = 0
        self.fail = fail

    def play(self, event: SoundEvent, *, volume: int) -> None:
        self.calls.append((event, volume))
        if self.fail:
            raise RuntimeError(r"C:\private\audio-device\driver failed")

    def stop(self) -> None:
        self.stop_calls += 1


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

    @staticmethod
    def write_variant_sound_pack(root: str) -> None:
        sound_root = Path(root) / "assets" / "sounds"
        sound_root.mkdir(parents=True, exist_ok=True)
        files = {}
        variants = {}
        for event in REQUIRED_SOUND_EVENTS:
            file_name = f"{event.value}.wav"
            files[event.value] = file_name
            with wave.open(str(sound_root / file_name), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(8000)
                writer.writeframes(b"\x00\x00" * 8)
            variants[event.value] = [
                {
                    "id": "1",
                    "file": file_name,
                    "label_uk": "Варіант 1",
                    "label_en": "Variant 1",
                }
            ]
        move2 = sound_root / "move2.wav"
        with wave.open(str(move2), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            writer.writeframes(b"\x01\x00" * 8)
        variants["move"].append(
            {
                "id": "2",
                "file": "move2.wav",
                "label_uk": "Хід 2",
                "label_en": "Move 2",
            }
        )

        for file_name, sample in (
            ("mate-ru.wav", b"\x02\x00"),
            ("draw-en.wav", b"\x03\x00"),
            ("draw-ru.wav", b"\x04\x00"),
            ("start-3d.wav", b"\x05\x00"),
            ("low-time-2.wav", b"\x06\x00"),
        ):
            with wave.open(str(sound_root / file_name), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(8000)
                writer.writeframes(sample * 8)
        variants["mate"].append(
            {
                "id": "ru",
                "file": "mate-ru.wav",
                "label_uk": "Мат — голос (рос.)",
                "label_en": "Checkmate — Russian voice",
            }
        )
        variants["draw"].extend(
            [
                {
                    "id": "en",
                    "file": "draw-en.wav",
                    "label_uk": "Нічия — голос (англ.)",
                    "label_en": "Draw — English voice",
                },
                {
                    "id": "ru",
                    "file": "draw-ru.wav",
                    "label_uk": "Нічия — голос (рос.)",
                    "label_en": "Draw — Russian voice",
                },
            ]
        )
        variants["start"].append(
            {
                "id": "3d",
                "file": "start-3d.wav",
                "label_uk": "Нова партія 3D",
                "label_en": "3D new game",
            }
        )
        variants["low_time"].append(
            {
                "id": "2",
                "file": "low-time-2.wav",
                "label_uk": "Мало часу — сигнал 2",
                "label_en": "Low time — alert 2",
            }
        )
        (sound_root / "manifest.json").write_text(
            json.dumps({"schema_version": 1, "files": files}),
            encoding="utf-8",
        )
        (sound_root / "variants.json").write_text(
            json.dumps({"schema_version": 1, "events": variants}),
            encoding="utf-8",
        )

    def test_v2_production_sound_variants_drive_the_real_playback_boundary(self) -> None:
        from acs.version2_release_app import create_version2_release_application

        adapters = []

        class _VariantPlayback:
            def __init__(self, resolver, *, cache_dir, variant_provider) -> None:
                self.resolver = resolver
                self.cache_dir = Path(cache_dir)
                self.variant_provider = variant_provider
                self.calls = []
                adapters.append(self)

            def play(self, event: SoundEvent, *, volume: int) -> None:
                self.calls.append((event, volume, self.variant_provider(event)))

            def stop(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_variant_sound_pack(td)
            data_root = root / "v2-user-data"
            with patch(
                "acs.version2_release_app.WindowsSoundPlaybackAdapter",
                _VariantPlayback,
            ):
                api, _application_factory, runtime, _native_runtime_factory = (
                    create_version2_release_application(
                        application_dir=root,
                        runtime_factory=_FakeRuntime,
                        data_root=data_root,
                        copy_text=lambda _value: None,
                        defer_ui=True,
                    )
                )
            try:
                state = api.get_sound_settings()
                move_variants = {
                    item["id"] for item in state["variants"][SoundEvent.MOVE.value]
                }
                start_variants = {
                    item["id"] for item in state["variants"][SoundEvent.START.value]
                }
                self.assertEqual(move_variants, {"1", "2"})
                self.assertEqual(start_variants, {"1", "3d"})
                self.assertTrue(api.set_sound_variant("move", "2")["ok"])
                self.assertTrue(api.set_sound_variant("start", "3d")["ok"])

                preview = api.preview_sound("move")
                start_preview = api.preview_sound("start")

                self.assertTrue(preview["ok"], preview)
                self.assertTrue(start_preview["ok"], start_preview)
                self.assertEqual(len(adapters), 1)
                self.assertIn(
                    (SoundEvent.MOVE, 80, "2"),
                    adapters[0].calls,
                )
                self.assertEqual(
                    adapters[0].calls[-1],
                    (SoundEvent.START, 80, "3d"),
                )
                selected = api.get_sound_settings()["selectedVariants"]
                self.assertEqual(selected[SoundEvent.MOVE.value], "2")
                self.assertEqual(selected[SoundEvent.START.value], "3d")
            finally:
                api.close_analysis()
                runtime.close()

            with patch(
                "acs.version2_release_app.WindowsSoundPlaybackAdapter",
                _VariantPlayback,
            ):
                api2, _application_factory2, runtime2, _native_runtime_factory2 = (
                    create_version2_release_application(
                        application_dir=root,
                        runtime_factory=_FakeRuntime,
                        data_root=data_root,
                        copy_text=lambda _value: None,
                        defer_ui=True,
                    )
                )
            try:
                restored = api2.get_sound_settings()
                self.assertEqual(
                    restored["selectedVariants"][SoundEvent.MOVE.value],
                    "2",
                )
                self.assertEqual(
                    restored["selectedVariants"][SoundEvent.START.value],
                    "3d",
                )

                preview2 = api2.preview_sound("move")
                start_preview2 = api2.preview_sound("start")

                self.assertTrue(preview2["ok"], preview2)
                self.assertTrue(start_preview2["ok"], start_preview2)
                self.assertEqual(len(adapters), 2)
                self.assertIn(
                    (SoundEvent.MOVE, 80, "2"),
                    adapters[1].calls,
                )
                self.assertEqual(
                    adapters[1].calls[-1],
                    (SoundEvent.START, 80, "3d"),
                )

                api2._settings.set("sound_move_variant", "missing")
                invalid_state = api2.get_sound_settings()
                self.assertEqual(
                    invalid_state["selectedVariants"][SoundEvent.MOVE.value],
                    "1",
                )
                invalid_preview = api2.preview_sound("move")
                self.assertTrue(invalid_preview["ok"], invalid_preview)
                self.assertEqual(
                    adapters[1].calls[-1],
                    (SoundEvent.MOVE, 80, "1"),
                )
            finally:
                api2.close_analysis()
                runtime2.close()

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

    def test_terminal_board_positions_use_specific_mate_and_draw_sounds(self) -> None:
        playback = _Playback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            try:
                for san in ("f3", "e5", "g4", "Qh4#"):
                    result = api.make_move(san)
                    self.assertTrue(result["ok"], result)
                events = [event for event, _volume in playback.calls]
                self.assertIn(SoundEvent.MATE, events)
                self.assertNotIn(SoundEvent.END, events)

                playback.calls.clear()
                api.board.set_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
                api.sans = ["Qf7"]
                api._resume_game_sound_after_takeback()
                api._play_latest_move()
                events = [event for event, _volume in playback.calls]
                self.assertEqual(events[-1], SoundEvent.DRAW)
                self.assertNotIn(SoundEvent.END, events)
            finally:
                api.close_analysis()
                runtime.close()

    def test_sound_settings_persist_drive_runtime_and_preview_is_real(self) -> None:
        playback = _Playback()
        with tempfile.TemporaryDirectory() as td:
            self.write_variant_sound_pack(td)
            settings_path = Path(td) / "settings.json"
            api, runtime = create_release_api(
                application_dir=td,
                runtime_factory=_FakeRuntime,
                sound_playback=playback,
                settings_path=settings_path,
            )
            try:
                self.assertTrue(api.set_sound_volume(35)["ok"])
                animation = api.set_newgame_animation_enabled(False)
                self.assertTrue(animation["ok"], animation)
                self.assertFalse(animation["newGameAnimation"])
                clock_mode = api.set_clock_sound_policy("both")
                self.assertTrue(clock_mode["ok"], clock_mode)
                self.assertEqual(clock_mode["tickPolicy"], "both")
                clock_limit = api.set_clock_sound_last_seconds(25)
                self.assertTrue(clock_limit["ok"], clock_limit)
                self.assertEqual(clock_limit["tickLastSeconds"], 25)
                low_mode = api.set_low_time_policy("both")
                self.assertTrue(low_mode["ok"], low_mode)
                self.assertEqual(low_mode["lowTimePolicy"], "both")
                low_limit = api.set_low_time_seconds(15)
                self.assertTrue(low_limit["ok"], low_limit)
                self.assertEqual(low_limit["lowTimeSeconds"], 15)
                selected = api.set_sound_variant("move", "2")
                self.assertTrue(selected["ok"], selected)
                self.assertEqual(selected["selectedVariants"]["move"], "2")
                mate_selected = api.set_sound_variant("mate", "ru")
                self.assertTrue(mate_selected["ok"], mate_selected)
                draw_selected = api.set_sound_variant("draw", "en")
                self.assertTrue(draw_selected["ok"], draw_selected)
                start_selected = api.set_sound_variant("start", "3d")
                self.assertTrue(start_selected["ok"], start_selected)
                low_selected = api.set_sound_variant("low_time", "2")
                self.assertTrue(low_selected["ok"], low_selected)
                self.assertEqual(low_selected["selectedVariants"]["mate"], "ru")
                self.assertEqual(low_selected["selectedVariants"]["draw"], "en")
                self.assertEqual(low_selected["selectedVariants"]["start"], "3d")
                self.assertEqual(low_selected["selectedVariants"]["low_time"], "2")
                mate_preview = api.preview_sound("mate")
                self.assertTrue(mate_preview["ok"], mate_preview)
                self.assertEqual(playback.calls[-1], (SoundEvent.MATE, 35))
                draw_preview = api.preview_sound("draw")
                self.assertTrue(draw_preview["ok"], draw_preview)
                self.assertEqual(playback.calls[-1], (SoundEvent.DRAW, 35))
                low_preview = api.preview_sound("low_time")
                self.assertTrue(low_preview["ok"], low_preview)
                self.assertEqual(playback.calls[-1], (SoundEvent.LOW_TIME, 35))
                self.assertGreater(api._clock_sound_not_before, 0.0)
                api._clock_sound_not_before = 0.0
                start_preview = api.preview_sound("start")
                self.assertTrue(start_preview["ok"], start_preview)
                self.assertEqual(playback.calls[-1], (SoundEvent.START, 35))
                self.assertGreater(api._clock_sound_not_before, 0.0)
                preview = api.preview_sound("capture")
                self.assertTrue(preview["ok"], preview)
                self.assertEqual(playback.calls[-1], (SoundEvent.CAPTURE, 35))
                before = len(playback.calls)
                self.assertTrue(api.set_sound_enabled(False)["ok"])
                self.assertEqual(playback.stop_calls, 1)
                self.assertEqual(api._clock_sound_not_before, 0.0)
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
                self.assertFalse(restored["newGameAnimation"])
                self.assertEqual(restored["volume"], 35)
                self.assertEqual(restored["tickPolicy"], "both")
                self.assertEqual(restored["tickLastSeconds"], 25)
                self.assertEqual(restored["lowTimePolicy"], "both")
                self.assertEqual(restored["lowTimeSeconds"], 15)
                self.assertEqual(restored["selectedVariants"]["move"], "2")
                self.assertEqual(restored["selectedVariants"]["mate"], "ru")
                self.assertEqual(restored["selectedVariants"]["draw"], "en")
                self.assertEqual(restored["selectedVariants"]["start"], "3d")
                self.assertEqual(restored["selectedVariants"]["low_time"], "2")
            finally:
                api2.close_analysis()
                runtime2.close()

    def test_zero_volume_stops_current_audio_without_touching_game_state(self) -> None:
        playback = _Playback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            try:
                self.assertTrue(api.make_move("e4")["ok"])
                fen_before = api.board.fen()
                history_before = tuple(api.sans)
                api._clock_sound_not_before = 999999999.0

                muted = api.set_sound_volume(0)

                self.assertTrue(muted["ok"], muted)
                self.assertEqual(playback.stop_calls, 1)
                self.assertEqual(api._clock_sound_not_before, 0.0)
                self.assertEqual(api.board.fen(), fen_before)
                self.assertEqual(tuple(api.sans), history_before)
            finally:
                api.close_analysis()
                runtime.close()

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

    def test_engine_first_move_does_not_interrupt_long_newgame_sound(self) -> None:
        playback = _Playback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            try:
                started = api.start_engine_game("black", 5, 1, 0)
                self.assertTrue(started["ok"], started)
                events = [event for event, _volume in playback.calls]
                self.assertEqual(events.count(SoundEvent.START), 1)
                self.assertEqual(events.count(SoundEvent.MOVE), 0)
                self.assertFalse(api._suppress_next_engine_move_sound_for_start)

                protected = api.clock_sound_pulse()
                self.assertTrue(protected["ok"], protected)
                self.assertFalse(protected["played"], protected)

                api._clock_sound_not_before = 0.0
                after_start = api.clock_sound_pulse()
                self.assertTrue(after_start["ok"], after_start)
                self.assertTrue(after_start["played"], after_start)
                self.assertEqual(playback.calls[-1], (SoundEvent.TICK, 80))
            finally:
                api.close_analysis()
                runtime.close()

    def test_live_clock_sound_uses_long_tick_segment_and_policy(self) -> None:
        playback = _Playback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            try:
                started = api.start_engine_game("white", 5, 1, 0)
                self.assertTrue(started["ok"], started)

                # Startup sound intentionally suppresses the immediate tick.
                # This assertion targets steady-state tick policy.
                api._clock_sound_not_before = 0.0
                first = api.clock_sound_pulse()
                self.assertTrue(first["ok"], first)
                self.assertTrue(first["played"], first)
                self.assertEqual(playback.calls[-1], (SoundEvent.TICK, 80))

                before = len(playback.calls)
                api._settings.set("tick_last_seconds", 10)
                limited = api.clock_sound_pulse()
                self.assertTrue(limited["ok"], limited)
                self.assertFalse(limited["played"], limited)
                self.assertEqual(len(playback.calls), before)

                api._settings.set("tick_policy", "off")
                disabled = api.clock_sound_pulse()
                self.assertTrue(disabled["disabled"], disabled)
                self.assertEqual(len(playback.calls), before)
            finally:
                api.close_analysis()
                runtime.close()

    def test_low_time_warning_is_independent_one_shot_and_rearms_above_threshold(self) -> None:
        playback = _Playback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            try:
                started = api.start_engine_game("white", 5, 1, 0)
                self.assertTrue(started["ok"], started)
                session = api._engine_session
                self.assertIsNotNone(session)
                clock = session._clock
                self.assertIsNotNone(clock)
                api._clock_sound_not_before = 0.0
                api._settings.set("tick_policy", "off")
                api._settings.set("low_time_policy", "my_turn")
                api._settings.set("low_time_seconds", 30)
                clock.set_remaining("w", 25_000)

                first = api.clock_sound_pulse()
                self.assertTrue(first["ok"], first)
                self.assertTrue(first["played"], first)
                self.assertEqual(first["event"], "low_time")
                self.assertEqual(playback.calls[-1], (SoundEvent.LOW_TIME, 80))
                self.assertGreater(api._clock_sound_not_before, 0.0)

                before = len(playback.calls)
                repeated = api.clock_sound_pulse()
                self.assertFalse(repeated["played"], repeated)
                self.assertEqual(len(playback.calls), before)

                api._clock_sound_not_before = 0.0
                clock.set_remaining("w", 35_000)
                api.clock_sound_pulse()
                clock.set_remaining("w", 25_000)
                replayed = api.clock_sound_pulse()
                self.assertTrue(replayed["played"], replayed)
                self.assertEqual(replayed["event"], "low_time")
                self.assertEqual(
                    [event for event, _volume in playback.calls].count(SoundEvent.LOW_TIME),
                    2,
                )
            finally:
                api.close_analysis()
                runtime.close()

    def test_low_time_warning_retries_after_sounds_are_reenabled(self) -> None:
        playback = _Playback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            try:
                started = api.start_engine_game("white", 5, 1, 0)
                self.assertTrue(started["ok"], started)
                session = api._engine_session
                self.assertIsNotNone(session)
                clock = session._clock
                self.assertIsNotNone(clock)
                api._clock_sound_not_before = 0.0
                api._settings.set("tick_policy", "off")
                api._settings.set("low_time_policy", "my_turn")
                api._settings.set("low_time_seconds", 30)
                clock.set_remaining("w", 25_000)

                self.assertTrue(api.set_sound_enabled(False)["ok"])
                muted = api.clock_sound_pulse()
                self.assertTrue(muted["disabled"], muted)
                self.assertFalse(muted["played"], muted)
                self.assertNotIn("w", api._low_time_warned_sides)

                self.assertTrue(api.set_sound_enabled(True)["ok"])
                retried = api.clock_sound_pulse()
                self.assertTrue(retried["played"], retried)
                self.assertEqual(retried["event"], "low_time")
                self.assertIn("w", api._low_time_warned_sides)
            finally:
                api.close_analysis()
                runtime.close()

    def test_clock_sound_pump_is_non_announcing_and_segment_sized(self) -> None:
        text = self.bootstrap
        self.assertIn("a.clock_sound_pulse()", text)
        self.assertIn("}, 3400);", text)
        self.assertIn("clockSoundPulseInFlight", text)
        self.assertIn("sound-low-time-policy", text)
        self.assertIn("sound-low-time-seconds", text)
        self.assertIn("'set_low_time_policy'", text)
        self.assertIn("'set_low_time_seconds'", text)

    def test_engine_resignation_emits_one_game_end_sound(self) -> None:
        playback = _Playback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            try:
                self.assertTrue(api.start_engine_game("white", 5, 0, 0)["ok"])
                resigned = api.resign_engine_game()
                self.assertTrue(resigned["ok"], resigned)
                self.assertEqual(
                    [event for event, _volume in playback.calls].count(SoundEvent.END),
                    1,
                )
                api.get_state()
                self.assertEqual(
                    [event for event, _volume in playback.calls].count(SoundEvent.END),
                    1,
                )
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
        # Chromium Ctrl+N is guarded once at document scope before async
        # keymap resolution; editable controls explicitly keep native input.
        self.assertIn("document.addEventListener('keydown'", text)
        self.assertIn("key === 'n'", text)
        self.assertIn("if (editing) return;", text)
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
        # Chromium Ctrl+N is guarded once at document scope before async
        # keymap resolution; editable controls explicitly keep native input.
        self.assertIn("document.addEventListener('keydown'", text)
        self.assertIn("key === 'n'", text)
        self.assertIn("if (editing) return;", text)
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
        # Chromium Ctrl+N is guarded once at document scope before async
        # keymap resolution; editable controls explicitly keep native input.
        self.assertIn("document.addEventListener('keydown'", text)
        self.assertIn("key === 'n'", text)
        self.assertIn("if (editing) return;", text)
        self.assertNotIn("window.addEventListener('keydown'", text)

    def test_new_game_visual_sequence_is_visual_only_interruptible_and_sound_timed(self) -> None:
        text = self.bootstrap
        self.assertIn("const NEW_GAME_IMPACTS_BY_VARIANT = Object.freeze({", text)
        matches = re.findall(
            r"'(1|3d)': Object\.freeze\(\[(.*?)\]\)",
            text,
            re.DOTALL,
        )
        js_by_variant = {
            variant: tuple(
                int(value.strip())
                for value in body.replace("\n", " ").split(",")
                if value.strip()
            )
            for variant, body in matches
        }
        self.assertEqual(js_by_variant["1"], NEW_GAME_IMPACT_MS)
        self.assertEqual(js_by_variant["3d"], NEW_GAME_3D_IMPACT_MS)
        self.assertIn("currentSoundState.selectedVariants.start", text)
        self.assertIn("if (!currentSoundState)", text)
        self.assertIn("currentSoundState.newGameAnimation === false", text)
        self.assertIn("soundStateLoadPromise = loadSoundState()", text)
        self.assertIn("await soundStateLoadPromise", text)
        self.assertIn("function startNewGameVisualSequence()", text)
        self.assertIn("function finishNewGameVisualSequence()", text)
        self.assertIn("prefers-reduced-motion: reduce", text)
        self.assertIn("piece.setAttribute('aria-hidden', 'true')", text)
        self.assertIn("document.addEventListener('keydown'", text)
        self.assertIn("document.addEventListener('pointerdown'", text)
        self.assertIn("window.startNewGameVisualSequence = startNewGameVisualSequence", text)
        self.assertIn("const baseApiAction = window.apiAction", text)
        self.assertIn("name === 'new_game'", text)
        self.assertIn("name === 'dispatch_action'", text)
        self.assertIn("String(args[0] || '') === 'file.new'", text)
        self.assertIn("await baseApiAction.call(this, name, ...args)", text)
        self.assertIn("await Promise.resolve();", text)
        self.assertIn("if (newGameVisualPending) newGameVisualPending = false;", text)
        recovery = text[text.index("const baseApiAction = window.apiAction"):text.index("const baseExecuteAction = window.executeAction")]
        self.assertLess(recovery.index("newGameVisualPending = true"), recovery.index("try {"))
        self.assertLess(recovery.index("await baseApiAction.call"), recovery.index("finally {"))
        self.assertLess(recovery.index("finally {"), recovery.index("newGameVisualPending = false"))
        self.assertIn("stage1-new-game-animating", text)
        self.assertIn("STANDARD_START_FEN", text)
        self.assertIn("Стандартну позицію встановлено.", text)
        self.assertIn("Standard position loaded.", text)
        self.assertIn("event.ctrlKey", text)
        self.assertIn("key === 'n'", text)
        self.assertNotIn("action.actionId !== 'file.new'", text)
        self.assertIn("if (!action || !action.actionId) return;", text)
        self.assertIn("void execute(action.actionId)", text)
        self.assertIn("void execute(action.actionId)", text)

        menu = (self.root / "acs" / "ui_native_menu.py").read_text(encoding="utf-8")
        self.assertIn('getattr(fn, "__name__", "") == "new_game"', menu)
        self.assertIn("window.startNewGameVisualSequence", menu)

    def test_webview_bootstrap_exposes_accessible_sound_controls_without_new_live_region(self) -> None:
        text = self.bootstrap
        for element_id in (
            "sound-settings", "sound-enabled", "sound-newgame-animation", "sound-volume",
            "sound-tick-policy", "sound-tick-last-seconds",
            "sound-low-time-policy", "sound-low-time-seconds",
            "move-error-announcements",
            "sound-settings-status",
        ):
            self.assertIn(element_id, text)
        self.assertIn("a.get_sound_settings", text)
        self.assertIn("'set_sound_enabled'", text)
        self.assertIn("'set_newgame_animation_enabled'", text)
        self.assertIn("'set_sound_volume'", text)
        self.assertIn("'set_clock_sound_policy'", text)
        self.assertIn("'set_clock_sound_last_seconds'", text)
        self.assertIn("'set_low_time_policy'", text)
        self.assertIn("'set_low_time_seconds'", text)
        self.assertIn("'set_move_error_announcements'", text)
        self.assertNotIn("sound-preview", text)
        self.assertNotIn("a.preview_sound", text)
        self.assertIn("mate:'Мат'", text)
        self.assertIn("draw:'Нічия'", text)
        self.assertIn("low_time:'Мало часу'", text)
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
