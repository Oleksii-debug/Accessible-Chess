from __future__ import annotations

import asyncio
import inspect
import unittest

from acs.agent_tools import ToolCall, ToolExecutor, ToolRisk
from acs.chess_agent_tools import (
    ChessAgentToolRegistry,
    ChessAgentToolsError,
    MediaAgentBridge,
)
from acs.chesscore import Board
from acs.media_application import (
    MediaApplicationCode,
    MediaApplicationError,
    MediaApplicationService,
)
from acs.media_core import (
    MediaChessLink,
    MediaChessSession,
    MediaContractError as CoreMediaContractError,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaSource,
    MediaSourceKind as CoreMediaSourceKind,
)
from dataclasses import dataclass
from enum import Enum


class FakePlayback:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | float | None]] = []

    def play(self) -> None:
        self.calls.append(("play", None))

    def pause(self) -> None:
        self.calls.append(("pause", None))

    def seek(self, position_ms: int) -> None:
        self.calls.append(("seek", position_ms))

    def set_rate(self, playback_rate: float) -> None:
        self.calls.append(("rate", playback_rate))


class FailingPlayback(FakePlayback):
    def seek(self, position_ms: int) -> None:
        raise RuntimeError("provider seek failed")


class ActiveFloat(float):
    def __float__(self):
        raise AssertionError("active numeric subclass must not execute")


def _link(
    timestamp_ms: int,
    chess_ref: str,
    *,
    status: MediaLinkStatus = MediaLinkStatus.CONFIRMED,
) -> MediaChessLink:
    return MediaChessLink(
        "media-nav",
        timestamp_ms,
        chess_ref,
        status=status,
        confidence=1.0,
        evidence="canonical navigation fixture",
    )


def _application(
    links: tuple[MediaChessLink, ...],
    *,
    duration_ms: int = 5000,
) -> MediaApplicationService:
    return MediaApplicationService(
        source=MediaSource(
            source_id="media-nav",
            title="Canonical navigation fixture",
            kind=CoreMediaSourceKind.LOCAL_FILE,
            duration_ms=duration_ms,
        ),
        timeline=MediaPositionTimeline("media-nav", links),
        session=MediaChessSession(MediaCursor("media-nav", 0), "analysis:independent"),
        restore_chess_ref=lambda _chess_ref: None,
    )


class _SourceKind(str, Enum):
    LOCAL_FILE = "local_file"


class _PlaybackState(str, Enum):
    PAUSED = "paused"


@dataclass(frozen=True)
class _ClockState:
    session_id: str
    source_id: str
    source_kind: _SourceKind
    position_ms: int
    duration_ms: int | None
    playback_state: _PlaybackState
    playback_rate: float
    revision: int


class _Clock:
    def __init__(self, state: _ClockState) -> None:
        self.state = state


def _clock(*, position_ms: int = 1500, duration_ms: int = 5000) -> _Clock:
    return _Clock(
        _ClockState(
            session_id="media-navigation-agent",
            source_id="media-nav",
            source_kind=_SourceKind.LOCAL_FILE,
            position_ms=position_ms,
            duration_ms=duration_ms,
            playback_state=_PlaybackState.PAUSED,
            playback_rate=1.0,
            revision=0,
        )
    )


class MediaAgentCanonicalNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.links = (
            _link(1000, "tree:previous"),
            _link(2000, "tree:next"),
            _link(3000, "tree:later"),
        )
        self.application = _application(self.links)
        self.clock = _clock()
        self.playback = FakePlayback()
        self.bridge = MediaAgentBridge(
            clock=self.clock,
            application=self.application,
            playback=self.playback,
        )

    def test_current_position_is_read_only_and_copyable(self) -> None:
        result = self.bridge.current_position()

        self.assertEqual(result["positionMs"], 1500)
        self.assertEqual(result["anchorPositionMs"], 1000)
        self.assertEqual(result["chessRef"], "tree:previous")
        self.assertEqual(result["qualification"], "confirmed")
        self.assertTrue(result["canRestore"])
        self.assertIs(type(result["accessibleText"]), str)
        self.assertIn("confirmed chess position", result["accessibleText"].lower())
        self.assertEqual(self.application.session.media_cursor.position_ms, 0)
        self.assertEqual(self.application.session.chess_ref, "analysis:independent")
        self.assertEqual(self.application.revision, 0)
        self.assertEqual(self.playback.calls, [])

    def test_direct_seek_is_application_validated_and_projects_target_status(self) -> None:
        result = self.bridge.seek(2500)

        self.assertEqual(result["requested"], "seek")
        self.assertEqual(result["positionMs"], 2500)
        self.assertEqual(result["anchorPositionMs"], 2000)
        self.assertEqual(result["chessRef"], "tree:next")
        self.assertEqual(result["qualification"], "confirmed")
        self.assertTrue(result["canRestore"])
        self.assertIn("confirmed chess position", result["accessibleText"].lower())
        self.assertEqual(self.playback.calls, [("seek", 2500)])
        self.assertEqual(self.clock.state.position_ms, 1500)
        self.assertEqual(self.application.session.media_cursor.position_ms, 0)
        self.assertEqual(self.application.session.chess_ref, "analysis:independent")
        self.assertEqual(self.application.revision, 0)

    def test_direct_seek_rejects_out_of_duration_before_provider_effect(self) -> None:
        application = _application(self.links, duration_ms=2500)
        playback = FakePlayback()
        bridge = MediaAgentBridge(
            clock=_clock(position_ms=1500, duration_ms=2500),
            application=application,
            playback=playback,
        )

        with self.assertRaises(CoreMediaContractError):
            bridge.seek(3000)

        self.assertEqual(playback.calls, [])
        self.assertEqual(application.session.media_cursor.position_ms, 0)
        self.assertEqual(application.revision, 0)

    def test_rate_control_is_bounded_provider_request_without_fake_clock_readback(self) -> None:
        result = self.bridge.set_rate(1.5)

        self.assertEqual(result["requested"], "set_rate")
        self.assertEqual(result["playbackRate"], 1.5)
        self.assertIn("1.5x", result["accessibleText"])
        self.assertEqual(self.playback.calls, [("rate", 1.5)])
        self.assertEqual(self.clock.state.playback_rate, 1.0)
        self.assertEqual(self.clock.state.revision, 0)
        self.assertEqual(self.application.revision, 0)

    def test_rate_control_rejects_invalid_values_before_provider_effect(self) -> None:
        invalid = (True, "1.5", 0.09, 8.01, float("nan"), float("inf"))
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ChessAgentToolsError):
                    self.bridge.set_rate(value)
        self.assertEqual(self.playback.calls, [])
        self.assertEqual(self.clock.state.playback_rate, 1.0)

    def test_next_move_requests_nearest_later_confirmed_anchor_only(self) -> None:
        result = self.bridge.next_move()

        self.assertEqual(result["requested"], "seek")
        self.assertEqual(result["direction"], "next")
        self.assertEqual(result["fromPositionMs"], 1500)
        self.assertEqual(result["positionMs"], 2000)
        self.assertEqual(result["chessRef"], "tree:next")
        self.assertIn("Next confirmed", result["accessibleText"])
        self.assertEqual(self.playback.calls, [("seek", 2000)])
        self.assertEqual(self.clock.state.position_ms, 1500)
        self.assertEqual(self.application.session.media_cursor.position_ms, 0)
        self.assertEqual(self.application.session.chess_ref, "analysis:independent")
        self.assertEqual(self.application.revision, 0)

    def test_previous_move_requests_nearest_earlier_confirmed_anchor_only(self) -> None:
        result = self.bridge.previous_move()

        self.assertEqual(result["requested"], "seek")
        self.assertEqual(result["direction"], "previous")
        self.assertEqual(result["fromPositionMs"], 1500)
        self.assertEqual(result["positionMs"], 1000)
        self.assertEqual(result["chessRef"], "tree:previous")
        self.assertIn("Previous confirmed", result["accessibleText"])
        self.assertEqual(self.playback.calls, [("seek", 1000)])
        self.assertEqual(self.application.revision, 0)

    def test_next_move_does_not_skip_nearest_unconfirmed_anchor(self) -> None:
        application = _application(
            (
                _link(1000, "tree:current"),
                _link(2000, "tree:candidate", status=MediaLinkStatus.CANDIDATE),
                _link(3000, "tree:later-confirmed"),
            )
        )
        playback = FakePlayback()
        bridge = MediaAgentBridge(
            clock=_clock(), application=application, playback=playback
        )

        with self.assertRaises(MediaApplicationError) as caught:
            bridge.next_move()

        self.assertEqual(
            caught.exception.code,
            MediaApplicationCode.NO_CONFIRMED_POSITION,
        )
        self.assertEqual(playback.calls, [])
        self.assertEqual(application.revision, 0)
        self.assertEqual(application.session.media_cursor.position_ms, 0)

    def test_next_move_does_not_guess_at_ambiguous_anchor(self) -> None:
        application = _application(
            (
                _link(1000, "tree:current"),
                _link(2000, "tree:a"),
                _link(2000, "tree:b"),
                _link(3000, "tree:later-confirmed"),
            )
        )
        playback = FakePlayback()
        bridge = MediaAgentBridge(
            clock=_clock(), application=application, playback=playback
        )

        with self.assertRaises(MediaApplicationError) as caught:
            bridge.next_move()

        self.assertEqual(caught.exception.code, MediaApplicationCode.AMBIGUOUS_POSITION)
        self.assertEqual(playback.calls, [])
        self.assertEqual(application.revision, 0)


    def test_next_move_stops_at_resync_barrier_without_provider_effect(self) -> None:
        from acs.media_core import MediaReconciliationState, MediaTimelineBarrier

        application = MediaApplicationService(
            source=MediaSource(
                source_id="media-nav",
                title="Barrier fixture",
                kind=CoreMediaSourceKind.LOCAL_FILE,
                duration_ms=5000,
            ),
            timeline=MediaPositionTimeline(
                "media-nav",
                (
                    _link(1000, "tree:current"),
                    _link(3000, "tree:later-confirmed"),
                ),
                barriers=(
                    MediaTimelineBarrier(
                        source_id="media-nav",
                        timestamp_ms=2000,
                        state=MediaReconciliationState.RESYNC_REQUIRED,
                        reason="provider discontinuity",
                    ),
                ),
            ),
            session=MediaChessSession(
                MediaCursor("media-nav", 0),
                "analysis:independent",
            ),
            restore_chess_ref=lambda _chess_ref: None,
        )
        playback = FakePlayback()
        bridge = MediaAgentBridge(
            clock=_clock(),
            application=application,
            playback=playback,
        )

        with self.assertRaises(MediaApplicationError) as caught:
            bridge.next_move()

        self.assertEqual(caught.exception.code, MediaApplicationCode.RESYNC_REQUIRED)
        self.assertEqual(playback.calls, [])
        self.assertEqual(application.revision, 0)

    def test_first_and_last_boundaries_are_explicit(self) -> None:
        first_bridge = MediaAgentBridge(
            clock=_clock(position_ms=1000),
            application=_application(self.links),
            playback=FakePlayback(),
        )
        with self.assertRaises(MediaApplicationError) as previous_error:
            first_bridge.previous_move()
        self.assertEqual(
            previous_error.exception.code,
            MediaApplicationCode.NO_PREVIOUS_POSITION,
        )

        last_playback = FakePlayback()
        last_bridge = MediaAgentBridge(
            clock=_clock(position_ms=3000),
            application=_application(self.links),
            playback=last_playback,
        )
        with self.assertRaises(MediaApplicationError) as next_error:
            last_bridge.next_move()
        self.assertEqual(
            next_error.exception.code,
            MediaApplicationCode.NO_NEXT_POSITION,
        )
        self.assertEqual(last_playback.calls, [])

    def test_navigation_rejects_timeline_anchor_outside_source_duration(self) -> None:
        application = _application(
            (
                _link(1000, "tree:current"),
                _link(3000, "tree:corrupt-out-of-range"),
            ),
            duration_ms=2500,
        )
        playback = FakePlayback()
        bridge = MediaAgentBridge(
            clock=_clock(position_ms=1500, duration_ms=2500),
            application=application,
            playback=playback,
        )

        with self.assertRaises(MediaApplicationError) as caught:
            bridge.next_move()

        self.assertEqual(caught.exception.code, MediaApplicationCode.INVALID_STATE)
        self.assertEqual(playback.calls, [])
        self.assertEqual(application.revision, 0)

    def test_provider_seek_failure_cannot_commit_application_or_clock_cursor(self) -> None:
        application = _application(self.links)
        clock = _clock()
        bridge = MediaAgentBridge(
            clock=clock,
            application=application,
            playback=FailingPlayback(),
        )

        with self.assertRaises(RuntimeError):
            bridge.next_move()

        self.assertEqual(clock.state.position_ms, 1500)
        self.assertEqual(application.session.media_cursor.position_ms, 0)
        self.assertEqual(application.session.chess_ref, "analysis:independent")
        self.assertEqual(application.revision, 0)

    def test_rate_control_rejects_active_numeric_subclass_before_provider_effect(self) -> None:
        with self.assertRaises(ChessAgentToolsError):
            self.bridge.set_rate(ActiveFloat(1.5))

        self.assertEqual(self.playback.calls, [])
        self.assertEqual(self.clock.state.playback_rate, 1.0)

    def test_bridge_rejects_known_clock_application_duration_mismatch(self) -> None:
        with self.assertRaises(ChessAgentToolsError):
            MediaAgentBridge(
                clock=_clock(position_ms=1500, duration_ms=4000),
                application=_application(self.links, duration_ms=5000),
                playback=FakePlayback(),
            )

    def test_argumentless_media_tools_reject_unexpected_payload_before_effect(self) -> None:
        executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=executor,
            board_provider=lambda: Board(),
            board_commands_provider=lambda: None,
            media=self.bridge,
        ).register_all()

        for tool_id in (
            "media.status",
            "media.current_position",
            "media.restore_position",
            "media.play",
            "media.pause",
            "media.next_move",
            "media.previous_move",
        ):
            with self.subTest(tool_id=tool_id):
                result = asyncio.run(
                    executor.execute(
                        ToolCall(
                            call_id=f"unexpected-{tool_id}",
                            tool_id=tool_id,
                            arguments={"unexpected": "ignored-before-fix"},
                        )
                    )
                )
                self.assertFalse(result.ok)
                self.assertEqual(result.error, "tool failed")

        self.assertEqual(self.playback.calls, [])
        self.assertEqual(self.application.revision, 0)
        self.assertEqual(self.application.session.media_cursor.position_ms, 0)

    def test_parameterized_media_tools_reject_extra_keys_before_effect(self) -> None:
        executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=executor,
            board_provider=lambda: Board(),
            board_commands_provider=lambda: None,
            media=self.bridge,
        ).register_all()

        seek = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="seek-extra",
                    tool_id="media.seek",
                    arguments={"position_ms": 2000, "unexpected": True},
                )
            )
        )
        rate = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="rate-extra",
                    tool_id="media.set_rate",
                    arguments={"playback_rate": 1.5, "unexpected": True},
                )
            )
        )

        self.assertFalse(seek.ok)
        self.assertFalse(rate.ok)
        self.assertEqual(seek.error, "tool failed")
        self.assertEqual(rate.error, "tool failed")
        self.assertEqual(self.playback.calls, [])

    def test_agent_navigation_contains_no_timeline_or_chess_rules_authority(self) -> None:
        source = "\n".join(
            inspect.getsource(method)
            for method in (
                MediaAgentBridge.current_position,
                MediaAgentBridge.seek,
                MediaAgentBridge.next_move,
                MediaAgentBridge.previous_move,
            )
        )
        self.assertIn("application.snapshot_at", source)
        self.assertIn("application.next_media_position", source)
        self.assertIn("application.previous_media_position", source)
        for forbidden in (
            ".timeline",
            "resolve_exact",
            "resolve_at_or_before",
            "restore_chess_ref",
            "Board(",
            "fen",
            "tree_path",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_registry_exposes_required_media_navigation_tools_and_risk(self) -> None:
        executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=executor,
            board_provider=lambda: Board(),
            board_commands_provider=lambda: None,
            media=self.bridge,
        ).register_all()
        specs = {spec.tool_id: spec for spec in executor.specs()}

        self.assertIn("media.current_position", specs)
        self.assertIn("media.set_rate", specs)
        self.assertIn("media.next_move", specs)
        self.assertIn("media.previous_move", specs)
        self.assertNotEqual(specs["media.current_position"].risk, ToolRisk.LOCAL_WRITE)
        self.assertEqual(specs["media.set_rate"].risk, ToolRisk.LOCAL_WRITE)
        self.assertEqual(specs["media.next_move"].risk, ToolRisk.LOCAL_WRITE)
        self.assertEqual(specs["media.previous_move"].risk, ToolRisk.LOCAL_WRITE)

        current = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="media-current-position",
                    tool_id="media.current_position",
                    arguments={},
                )
            )
        )
        self.assertTrue(current.ok, current.error)
        self.assertEqual(current.output["chessRef"], "tree:previous")
        self.assertNotIn("fen", current.output)
        self.assertNotIn("treePath", current.output)

        rate = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="media-rate",
                    tool_id="media.set_rate",
                    arguments={"playback_rate": 1.25},
                )
            )
        )
        self.assertTrue(rate.ok, rate.error)
        self.assertEqual(rate.output["playbackRate"], 1.25)

        next_result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="media-next-move",
                    tool_id="media.next_move",
                    arguments={},
                )
            )
        )
        self.assertTrue(next_result.ok, next_result.error)
        self.assertEqual(next_result.output["positionMs"], 2000)
        self.assertNotIn("fen", next_result.output)
        self.assertNotIn("treePath", next_result.output)


if __name__ == "__main__":
    unittest.main()
