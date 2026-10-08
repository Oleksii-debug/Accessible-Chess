from __future__ import annotations

"""Versioned presentation-only design profiles for Accessible Chess Sections 43–45.

This module deliberately owns no chess, GameTree, engine, media, classroom or
account state.  It defines one serializable visual/workspace schema shared by
Windows WebView2 and the browser client.  Consumers may preview a profile, but
only the trusted application host persists it.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
import json
from types import MappingProxyType
from typing import Mapping

from .visual_preferences import BoardOrientation, BoardVisualPreferences, CoordinateMode

DESIGN_SCHEMA_VERSION = 1
MAX_PROFILE_NAME = 64
MAX_LAYOUTS = 16
MAX_PANELS_PER_LAYOUT = 24
_ALLOWED_WORKSPACES = frozenset(
    {"chess", "library", "books", "training", "teacher", "student", "media"}
)
_ALLOWED_PANELS = frozenset(
    {
        "board", "moves", "analysis", "game_info", "context", "search", "results",
        "reader", "toc", "exercise", "progress", "students", "lesson", "player",
        "timeline", "chat", "details",
    }
)


class AppTheme(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"
    HIGH_CONTRAST = "high_contrast"


class Density(StrEnum):
    COMFORTABLE = "comfortable"
    COMPACT = "compact"
    PRESENTATION = "presentation"


class DesignProfileId(StrEnum):
    CLASSIC = "classic"
    TOURNAMENT = "tournament"
    COACH = "coach"
    CLASSROOM_PRESENTATION = "classroom_presentation"
    LOW_VISION = "low_vision"
    HIGH_CONTRAST = "high_contrast"


def _bounded_text(value: object, label: str, *, maximum: int = MAX_PROFILE_NAME) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be text")
    if value != value.strip() or not value or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} is invalid")
    if any(ord(ch) < 32 or 0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise ValueError(f"{label} contains invalid characters")
    return value


def _exact_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an exact integer in {minimum}..{maximum}")
    return value


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    workspace: str
    panel_order: tuple[str, ...]
    collapsed: tuple[str, ...] = ()
    primary_percent: int = 62

    def __post_init__(self) -> None:
        if type(self.workspace) is not str or self.workspace not in _ALLOWED_WORKSPACES:
            raise ValueError("unsupported workspace")
        if type(self.panel_order) is not tuple or not self.panel_order:
            raise TypeError("panel_order must be a non-empty tuple")
        if len(self.panel_order) > MAX_PANELS_PER_LAYOUT:
            raise ValueError("workspace contains too many panels")
        if any(type(item) is not str or item not in _ALLOWED_PANELS for item in self.panel_order):
            raise ValueError("workspace contains an unsupported panel")
        if len(set(self.panel_order)) != len(self.panel_order):
            raise ValueError("workspace panel_order contains duplicates")
        if type(self.collapsed) is not tuple:
            raise TypeError("collapsed must be a tuple")
        if any(type(item) is not str or item not in self.panel_order for item in self.collapsed):
            raise ValueError("collapsed panels must belong to panel_order")
        if len(set(self.collapsed)) != len(self.collapsed):
            raise ValueError("collapsed contains duplicates")
        _exact_int(self.primary_percent, "primary_percent", 35, 80)

    def as_dict(self) -> dict[str, object]:
        return {
            "workspace": self.workspace,
            "panel_order": list(self.panel_order),
            "collapsed": list(self.collapsed),
            "primary_percent": self.primary_percent,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorkspaceLayout":
        if not isinstance(value, Mapping) or set(value) != {
            "workspace", "panel_order", "collapsed", "primary_percent"
        }:
            raise ValueError("invalid workspace layout object")
        order, collapsed = value["panel_order"], value["collapsed"]
        if type(order) is not list or type(collapsed) is not list:
            raise TypeError("workspace layout arrays are invalid")
        return cls(
            workspace=value["workspace"],  # type: ignore[arg-type]
            panel_order=tuple(order),  # type: ignore[arg-type]
            collapsed=tuple(collapsed),  # type: ignore[arg-type]
            primary_percent=value["primary_percent"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class DesignPreferences:
    profile_name: str
    theme: AppTheme = AppTheme.SYSTEM
    density: Density = Density.COMFORTABLE
    text_scale_percent: int = 100
    app_zoom_percent: int = 100
    highlight_percent: int = 100
    board: BoardVisualPreferences = BoardVisualPreferences()
    sound_enabled: bool = True
    layouts: tuple[WorkspaceLayout, ...] = ()
    schema_version: int = DESIGN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != DESIGN_SCHEMA_VERSION:
            raise ValueError("unsupported design schema_version")
        object.__setattr__(self, "profile_name", _bounded_text(self.profile_name, "profile_name"))
        if not isinstance(self.theme, AppTheme):
            raise TypeError("theme must be AppTheme")
        if not isinstance(self.density, Density):
            raise TypeError("density must be Density")
        _exact_int(self.text_scale_percent, "text_scale_percent", 75, 250)
        _exact_int(self.app_zoom_percent, "app_zoom_percent", 75, 250)
        _exact_int(self.highlight_percent, "highlight_percent", 50, 200)
        if type(self.board) is not BoardVisualPreferences:
            raise TypeError("board must be BoardVisualPreferences")
        if type(self.sound_enabled) is not bool:
            raise TypeError("sound_enabled must be bool")
        if type(self.layouts) is not tuple or len(self.layouts) > MAX_LAYOUTS:
            raise TypeError("layouts must be a bounded tuple")
        names = [item.workspace for item in self.layouts]
        if len(names) != len(set(names)):
            raise ValueError("duplicate workspace layout")
        if any(type(item) is not WorkspaceLayout for item in self.layouts):
            raise TypeError("layouts must contain WorkspaceLayout")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile_name": self.profile_name,
            "theme": self.theme.value,
            "density": self.density.value,
            "text_scale_percent": self.text_scale_percent,
            "app_zoom_percent": self.app_zoom_percent,
            "highlight_percent": self.highlight_percent,
            "sound_enabled": self.sound_enabled,
            "board": self.board.as_dict(),
            "layouts": [item.as_dict() for item in self.layouts],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DesignPreferences":
        expected = {
            "schema_version", "profile_name", "theme", "density",
            "text_scale_percent", "app_zoom_percent", "highlight_percent",
            "sound_enabled", "board", "layouts",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("invalid design preference object")
        layouts = value["layouts"]
        if type(layouts) is not list:
            raise TypeError("layouts must be an array")
        try:
            theme = AppTheme(value["theme"])
            density = Density(value["density"])
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown design preference enum") from exc
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            profile_name=value["profile_name"],  # type: ignore[arg-type]
            theme=theme,
            density=density,
            text_scale_percent=value["text_scale_percent"],  # type: ignore[arg-type]
            app_zoom_percent=value["app_zoom_percent"],  # type: ignore[arg-type]
            highlight_percent=value["highlight_percent"],  # type: ignore[arg-type]
            sound_enabled=value["sound_enabled"],  # type: ignore[arg-type]
            board=BoardVisualPreferences.from_dict(value["board"]),  # type: ignore[arg-type]
            layouts=tuple(WorkspaceLayout.from_dict(item) for item in layouts),  # type: ignore[arg-type]
        )

    def with_layout(self, layout: WorkspaceLayout) -> "DesignPreferences":
        current = {item.workspace: item for item in self.layouts}
        current[layout.workspace] = layout
        return replace(self, layouts=tuple(current[key] for key in sorted(current)))


_DEFAULT_LAYOUTS = (
    WorkspaceLayout("chess", ("board", "moves", "analysis", "game_info", "context"), (), 64),
    WorkspaceLayout("library", ("search", "results", "details"), (), 45),
    WorkspaceLayout("books", ("reader", "toc", "board"), ("board",), 68),
    WorkspaceLayout("training", ("exercise", "board", "analysis", "progress"), ("analysis",), 58),
    WorkspaceLayout("teacher", ("board", "students", "lesson", "chat"), ("chat",), 62),
    WorkspaceLayout("student", ("board", "lesson", "progress"), (), 70),
    WorkspaceLayout("media", ("player", "timeline", "board", "analysis"), ("analysis",), 58),
)


def _board(
    theme: str,
    pieces: str = "classic",
    *,
    scale: int = 100,
    piece_scale: int = 92,
    coordinates: CoordinateMode = CoordinateMode.EDGES,
    reduced_motion: bool = False,
) -> BoardVisualPreferences:
    return BoardVisualPreferences(
        board_theme_id=theme,
        piece_theme_id=pieces,
        coordinate_mode=coordinates,
        orientation=BoardOrientation.WHITE,
        board_scale_percent=scale,
        piece_scale_percent=piece_scale,
        show_last_move=True,
        reduced_motion=reduced_motion,
    )


_PRESETS = MappingProxyType({
    DesignProfileId.CLASSIC.value: DesignPreferences(
        "Classic", AppTheme.SYSTEM, Density.COMFORTABLE, 100, 100, 100,
        _board("classic"), True, _DEFAULT_LAYOUTS,
    ),
    DesignProfileId.TOURNAMENT.value: DesignPreferences(
        "Tournament", AppTheme.DARK, Density.COMPACT, 100, 100, 115,
        _board("tournament_blue"), True, _DEFAULT_LAYOUTS,
    ),
    DesignProfileId.COACH.value: DesignPreferences(
        "Coach", AppTheme.SYSTEM, Density.COMFORTABLE, 110, 110, 125,
        _board("classic_wood", scale=110), True, _DEFAULT_LAYOUTS,
    ),
    DesignProfileId.CLASSROOM_PRESENTATION.value: DesignPreferences(
        "Classroom Presentation", AppTheme.LIGHT, Density.PRESENTATION, 150, 150, 150,
        _board("tournament_blue", scale=135, piece_scale=110, coordinates=CoordinateMode.EVERY_SQUARE),
        True, _DEFAULT_LAYOUTS,
    ),
    DesignProfileId.LOW_VISION.value: DesignPreferences(
        "Low Vision", AppTheme.HIGH_CONTRAST, Density.COMFORTABLE, 175, 175, 175,
        _board("high_contrast", scale=150, piece_scale=120, coordinates=CoordinateMode.EVERY_SQUARE, reduced_motion=True),
        True, _DEFAULT_LAYOUTS,
    ),
    DesignProfileId.HIGH_CONTRAST.value: DesignPreferences(
        "High Contrast", AppTheme.HIGH_CONTRAST, Density.COMFORTABLE, 125, 125, 175,
        _board("high_contrast", scale=120, coordinates=CoordinateMode.EDGES, reduced_motion=True),
        True, _DEFAULT_LAYOUTS,
    ),
})


def preset_profiles() -> Mapping[str, DesignPreferences]:
    return _PRESETS


def preset_profile(profile_id: str) -> DesignPreferences:
    if type(profile_id) is not str or profile_id not in _PRESETS:
        raise KeyError("unknown design profile")
    return _PRESETS[profile_id]


def encode_preferences(value: DesignPreferences) -> str:
    if type(value) is not DesignPreferences:
        raise TypeError("value must be DesignPreferences")
    return json.dumps(value.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_preferences(text: str) -> DesignPreferences:
    if type(text) is not str or not text or len(text) > 64 * 1024 or "\x00" in text:
        raise ValueError("invalid design profile JSON")
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid design profile JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError("design profile JSON must be an object")
    return DesignPreferences.from_dict(value)


def safe_preferences_or_default(text: object, *, fallback: str = DesignProfileId.CLASSIC.value) -> DesignPreferences:
    try:
        return decode_preferences(text) if type(text) is str else preset_profile(fallback)
    except (TypeError, ValueError, KeyError):
        return preset_profile(fallback)


def exported_profile(value: DesignPreferences) -> dict[str, object]:
    """Return path-free JSON-safe data suitable for user export/Web synchronization."""
    payload = value.as_dict()
    forbidden = {"path", "directory", "token", "secret", "password", "api_key"}
    stack: list[object] = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                if str(key).casefold() in forbidden:
                    raise ValueError("design export contains a private field")
                stack.append(item)
        elif isinstance(current, list):
            stack.extend(current)
    return payload
