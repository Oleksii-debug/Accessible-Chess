from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SoundEvent(str, Enum):
    """Presentation-neutral semantic sound events.

    These values are stable application event IDs. They deliberately contain no
    file paths, audio APIs, platform checks, localization, or playback policy.
    Infrastructure may map them to WAV assets, system sounds, haptics, or other
    output without changing chess/domain code.
    """

    MOVE = "move"
    CAPTURE = "capture"
    CHECK = "check"
    CASTLE = "castle"
    PROMOTION = "promotion"
    ILLEGAL = "illegal"
    START = "start"
    END = "end"


@dataclass(frozen=True)
class MoveSoundFacts:
    """Facts produced by chess/application logic after a move attempt.

    A successful move always produces one primary mechanical event (move,
    capture, castle, or promotion). Check and game-end are additional semantic
    events so presentation code can decide whether to play, queue, speak, or
    otherwise expose them.
    """

    legal: bool = True
    capture: bool = False
    check: bool = False
    castle: bool = False
    promotion: bool = False
    game_ended: bool = False

    def __post_init__(self) -> None:
        if not self.legal and any(
            (self.capture, self.check, self.castle, self.promotion, self.game_ended)
        ):
            raise ValueError("illegal move facts cannot also describe a successful move")
        if self.castle and self.capture:
            raise ValueError("castling cannot also be a capture")
        if self.castle and self.promotion:
            raise ValueError("castling cannot also be a promotion")


class SoundEventPolicy:
    """Pure deterministic mapping from chess facts to semantic sound events."""

    @staticmethod
    def game_start() -> tuple[SoundEvent, ...]:
        return (SoundEvent.START,)

    @staticmethod
    def game_end() -> tuple[SoundEvent, ...]:
        return (SoundEvent.END,)

    @staticmethod
    def illegal() -> tuple[SoundEvent, ...]:
        return (SoundEvent.ILLEGAL,)

    @staticmethod
    def for_move(facts: MoveSoundFacts) -> tuple[SoundEvent, ...]:
        if not facts.legal:
            return (SoundEvent.ILLEGAL,)

        events: list[SoundEvent] = []

        # Exactly one primary physical-action event. Promotion outranks capture
        # because a capturing promotion is still semantically a promotion; the
        # capture fact remains available to any richer presentation separately.
        if facts.promotion:
            events.append(SoundEvent.PROMOTION)
        elif facts.castle:
            events.append(SoundEvent.CASTLE)
        elif facts.capture:
            events.append(SoundEvent.CAPTURE)
        else:
            events.append(SoundEvent.MOVE)

        if facts.check:
            events.append(SoundEvent.CHECK)
        if facts.game_ended:
            events.append(SoundEvent.END)

        return tuple(events)
