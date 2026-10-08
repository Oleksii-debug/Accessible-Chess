from dataclasses import FrozenInstanceError

import pytest

from acs.clock_service import ClockSnapshot, ClockState, TimeControl
from acs.game_lifecycle import GameStatus, LifecycleSnapshot
from acs.multiplayer_coordination import GameIntent, GameIntentKind, MultiplayerGameSnapshot
from acs.multiplayer_spectator import SpectatorGameView, spectator_view
from acs.player_directory import DirectoryPresenceSnapshot, DirectoryPresenceState, PlayerDirectoryEntry, PlayerDirectorySnapshot


def game_snapshot() -> MultiplayerGameSnapshot:
    return MultiplayerGameSnapshot(
        game_id="game-1",
        sequence=7,
        white_player_id="alice",
        black_player_id="bob",
        time_control=TimeControl(0),
        position_revision="pos:7",
        side_to_move="w",
        clock=ClockSnapshot(0, 0, None, ClockState.STOPPED),
        lifecycle=LifecycleSnapshot(GameStatus.ACTIVE, None, None, None),
    )


def test_spectator_projection_is_read_only_and_tracks_authoritative_revision():
    source = game_snapshot()
    view = spectator_view(source)
    assert isinstance(view, SpectatorGameView)
    assert view.game_id == "game-1"
    assert view.sequence == 7
    assert view.position_revision == "pos:7"
    assert view.status == "active"
    assert not hasattr(view, "move")
    assert not hasattr(view, "apply")
    with pytest.raises(FrozenInstanceError):
        view.sequence = 8


def test_online_move_is_an_intent_not_local_chess_authority():
    source = game_snapshot()
    intent = GameIntent(game_id=source.game_id, actor_id="alice", expected_sequence=source.sequence, kind=GameIntentKind.MOVE, move_text="e4")
    assert intent.game_id == source.game_id
    assert intent.expected_sequence == 7
    assert source.sequence == 7
    assert source.position_revision == "pos:7"


def test_social_presence_is_account_layer_data_not_game_truth():
    directory = PlayerDirectorySnapshot(
        revision=2,
        players=(PlayerDirectoryEntry("alice", "Alice"),),
        presences=(DirectoryPresenceSnapshot("alice", DirectoryPresenceState.AVAILABLE, 1),),
    )
    assert directory.player("alice").display_name == "Alice"
    assert directory.presence("alice").state is DirectoryPresenceState.AVAILABLE
    assert not hasattr(directory, "position_revision")
    assert not hasattr(directory, "clock")
