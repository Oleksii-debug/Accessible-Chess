from __future__ import annotations

from dataclasses import dataclass

from .multiplayer_coordination import MultiplayerContractError, MultiplayerGameSnapshot


@dataclass(frozen=True)
class SpectatorGameView:
    """Read-only presentation projection of server-authoritative online game state."""

    game_id: str
    sequence: int
    white_player_id: str
    black_player_id: str
    position_revision: str
    side_to_move: str
    white_ms: int
    black_ms: int
    status: str
    result: str | None
    white_presence: str
    black_presence: str

    @classmethod
    def from_game(cls, snapshot: MultiplayerGameSnapshot) -> "SpectatorGameView":
        if not isinstance(snapshot, MultiplayerGameSnapshot):
            raise MultiplayerContractError("spectator projection requires a typed game snapshot")
        outcome = snapshot.lifecycle.outcome
        return cls(
            game_id=snapshot.game_id,
            sequence=snapshot.sequence,
            white_player_id=snapshot.white_player_id,
            black_player_id=snapshot.black_player_id,
            position_revision=snapshot.position_revision,
            side_to_move=snapshot.side_to_move,
            white_ms=snapshot.clock.white_ms,
            black_ms=snapshot.clock.black_ms,
            status=snapshot.lifecycle.status.value,
            result=None if outcome is None else outcome.result,
            white_presence=snapshot.white_presence.value,
            black_presence=snapshot.black_presence.value,
        )


def spectator_view(snapshot: MultiplayerGameSnapshot) -> SpectatorGameView:
    """Project authoritative state without exposing any mutation command."""
    return SpectatorGameView.from_game(snapshot)
