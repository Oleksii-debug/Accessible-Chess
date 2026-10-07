from __future__ import annotations

"""Safe tactile input routing and durable device-profile selection.

This module is chess-rule-free. Hardware input is translated only into
already-registered application commands. Board-square routing is limited to
cursor/navigation commands so a tactile event cannot play a move, edit a
position, undo/redo, or otherwise mutate canonical chess state.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Protocol


SCHEMA_VERSION = 1
MAX_SETTINGS_BYTES = 64 * 1024
MAX_DEVICES = 128
MAX_BUTTONS = 64
_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_DEVICE_ID_MAX = 128


class TactileInputError(ValueError):
    """Invalid, unsupported, stale, or unsafe tactile input."""


class TactileSettingsError(TactileInputError):
    """Persistent tactile settings are malformed or unsafe."""


class TactileInputKind(str, Enum):
    ROUTING = "routing"
    TOUCH = "touch"
    BUTTON = "button"


class TactileOrientation(str, Enum):
    WHITE_BOTTOM = "white_bottom"
    BLACK_BOTTOM = "black_bottom"


class ActionRegistryPort(Protocol):
    def definition(self, action_id: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class TactileDeviceCapabilities:
    rows: int
    columns: int
    routing: bool = False
    touch: bool = False
    buttons: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if type(self.rows) is not int or not 1 <= self.rows <= 512:
            raise TactileInputError("device rows must be in 1..512")
        if type(self.columns) is not int or not 1 <= self.columns <= 512:
            raise TactileInputError("device columns must be in 1..512")
        if type(self.routing) is not bool or type(self.touch) is not bool:
            raise TactileInputError("device input capability flags must be boolean")
        if type(self.buttons) is not frozenset or len(self.buttons) > MAX_BUTTONS:
            raise TactileInputError("device buttons must be a bounded frozenset")
        for button in self.buttons:
            _validate_button_name(button)


@dataclass(frozen=True, slots=True)
class TactileDeviceProfile:
    profile_id: str
    label: str
    rows: int
    columns: int
    board_top: int = 0
    board_left: int = 0
    row_stride: int = 1
    column_stride: int = 1
    orientation: TactileOrientation = TactileOrientation.WHITE_BOTTOM
    routing_enabled: bool = True
    touch_enabled: bool = True
    button_actions: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _validate_profile_id(self.profile_id)
        if type(self.label) is not str or not self.label.strip() or len(self.label) > 128:
            raise TactileInputError("profile label must be non-empty bounded text")
        for name, value in (
            ("rows", self.rows),
            ("columns", self.columns),
            ("board_top", self.board_top),
            ("board_left", self.board_left),
            ("row_stride", self.row_stride),
            ("column_stride", self.column_stride),
        ):
            if type(value) is not int:
                raise TactileInputError(f"profile {name} must be an integer")
        if not 1 <= self.rows <= 512 or not 1 <= self.columns <= 512:
            raise TactileInputError("profile geometry must be in 1..512")
        if self.board_top < 0 or self.board_left < 0:
            raise TactileInputError("profile board offsets cannot be negative")
        if not 1 <= self.row_stride <= 64 or not 1 <= self.column_stride <= 64:
            raise TactileInputError("profile board stride must be in 1..64")
        if self.board_top + 7 * self.row_stride >= self.rows:
            raise TactileInputError("profile board rows do not fit device geometry")
        if self.board_left + 7 * self.column_stride >= self.columns:
            raise TactileInputError("profile board columns do not fit device geometry")
        if type(self.orientation) is not TactileOrientation:
            raise TactileInputError("profile orientation is invalid")
        if type(self.routing_enabled) is not bool or type(self.touch_enabled) is not bool:
            raise TactileInputError("profile input flags must be boolean")
        if type(self.button_actions) is not tuple or len(self.button_actions) > MAX_BUTTONS:
            raise TactileInputError("profile button map must be a bounded tuple")
        seen: set[str] = set()
        for entry in self.button_actions:
            if type(entry) is not tuple or len(entry) != 2:
                raise TactileInputError("profile button map entries must be pairs")
            button, action_id = entry
            _validate_button_name(button)
            _validate_action_id(action_id)
            if button in seen:
                raise TactileInputError("profile button map contains duplicate buttons")
            seen.add(button)

    @property
    def button_map(self) -> dict[str, str]:
        return dict(self.button_actions)

    def compatible_with(self, capabilities: TactileDeviceCapabilities) -> bool:
        if not isinstance(capabilities, TactileDeviceCapabilities):
            return False
        if capabilities.rows < self.rows or capabilities.columns < self.columns:
            return False
        required_buttons = {name for name, _ in self.button_actions}
        return required_buttons.issubset(capabilities.buttons)

    def square_for_cell(self, row: int, column: int) -> str | None:
        if type(row) is not int or type(column) is not int:
            raise TactileInputError("tactile cell coordinates must be integers")
        if not 0 <= row < self.rows or not 0 <= column < self.columns:
            raise TactileInputError("tactile cell is outside the configured profile")
        relative_row = row - self.board_top
        relative_column = column - self.board_left
        if relative_row < 0 or relative_column < 0:
            return None
        if relative_row % self.row_stride or relative_column % self.column_stride:
            return None
        board_row = relative_row // self.row_stride
        board_column = relative_column // self.column_stride
        if not 0 <= board_row < 8 or not 0 <= board_column < 8:
            return None
        if self.orientation is TactileOrientation.WHITE_BOTTOM:
            file_index = board_column
            rank = 8 - board_row
        else:
            file_index = 7 - board_column
            rank = 1 + board_row
        return f"{chr(ord('a') + file_index)}{rank}"


class TactileProfileRegistry:
    def __init__(self, profiles: Iterable[TactileDeviceProfile]) -> None:
        items = tuple(profiles)
        if not items:
            raise TactileInputError("at least one tactile device profile is required")
        if len(items) > 64:
            raise TactileInputError("too many tactile device profiles")
        by_id: dict[str, TactileDeviceProfile] = {}
        for profile in items:
            if not isinstance(profile, TactileDeviceProfile):
                raise TactileInputError("invalid tactile device profile")
            if profile.profile_id in by_id:
                raise TactileInputError("duplicate tactile device profile id")
            by_id[profile.profile_id] = profile
        self._profiles = by_id

    def profiles(self) -> tuple[TactileDeviceProfile, ...]:
        return tuple(self._profiles.values())

    def get(self, profile_id: str) -> TactileDeviceProfile:
        _validate_profile_id(profile_id)
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise TactileInputError("unknown tactile device profile") from exc

    def first_compatible(
        self, capabilities: TactileDeviceCapabilities
    ) -> TactileDeviceProfile | None:
        for profile in self._profiles.values():
            if profile.compatible_with(capabilities):
                return profile
        return None


@dataclass(frozen=True, slots=True)
class TactileSettings:
    default_profile_id: str | None = None
    reconnect_enabled: bool = True
    device_profiles: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.default_profile_id is not None:
            _validate_profile_id(self.default_profile_id)
        if type(self.reconnect_enabled) is not bool:
            raise TactileSettingsError("reconnect_enabled must be boolean")
        if type(self.device_profiles) is not tuple or len(self.device_profiles) > MAX_DEVICES:
            raise TactileSettingsError("device profile settings are not bounded")
        seen: set[str] = set()
        for item in self.device_profiles:
            if type(item) is not tuple or len(item) != 2:
                raise TactileSettingsError("device profile settings must be pairs")
            device_id, profile_id = item
            _validate_device_id(device_id)
            _validate_profile_id(profile_id)
            if device_id in seen:
                raise TactileSettingsError("duplicate device id in tactile settings")
            seen.add(device_id)

    def profile_for(self, device_id: str) -> str | None:
        _validate_device_id(device_id)
        return dict(self.device_profiles).get(device_id)

    def with_device_profile(self, device_id: str, profile_id: str) -> "TactileSettings":
        _validate_device_id(device_id)
        _validate_profile_id(profile_id)
        values = dict(self.device_profiles)
        values[device_id] = profile_id
        if len(values) > MAX_DEVICES:
            raise TactileSettingsError("too many remembered tactile devices")
        return TactileSettings(
            default_profile_id=self.default_profile_id,
            reconnect_enabled=self.reconnect_enabled,
            device_profiles=tuple(sorted(values.items())),
        )

    def with_default_profile(self, profile_id: str | None) -> "TactileSettings":
        if profile_id is not None:
            _validate_profile_id(profile_id)
        return TactileSettings(
            default_profile_id=profile_id,
            reconnect_enabled=self.reconnect_enabled,
            device_profiles=self.device_profiles,
        )

    def with_reconnect_enabled(self, enabled: bool) -> "TactileSettings":
        if type(enabled) is not bool:
            raise TactileSettingsError("reconnect_enabled must be boolean")
        return TactileSettings(
            default_profile_id=self.default_profile_id,
            reconnect_enabled=enabled,
            device_profiles=self.device_profiles,
        )


class TactileDeviceSettingsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> TactileSettings:
        path = self.path
        try:
            info = path.lstat()
        except FileNotFoundError:
            return TactileSettings()
        except OSError as exc:
            raise TactileSettingsError("tactile settings could not be inspected") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise TactileSettingsError("tactile settings must be a regular file")
        if info.st_size > MAX_SETTINGS_BYTES:
            raise TactileSettingsError("tactile settings file is too large")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise TactileSettingsError("tactile settings could not be read") from exc
        if len(data) > MAX_SETTINGS_BYTES:
            raise TactileSettingsError("tactile settings file is too large")
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TactileSettingsError(
                "tactile settings are not valid UTF-8 JSON"
            ) from exc
        return self._decode(payload)

    def save(self, settings: TactileSettings) -> None:
        if not isinstance(settings, TactileSettings):
            raise TypeError("settings must be TactileSettings")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "default_profile_id": settings.default_profile_id,
            "reconnect_enabled": settings.reconnect_enabled,
            "device_profiles": [
                {"device_id": device_id, "profile_id": profile_id}
                for device_id, profile_id in settings.device_profiles
            ],
        }
        encoded = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if len(encoded) > MAX_SETTINGS_BYTES:
            raise TactileSettingsError("tactile settings are too large")

        parent = self.path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            parent_info = parent.lstat()
        except OSError as exc:
            raise TactileSettingsError(
                "tactile settings directory is unavailable"
            ) from exc
        if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
            raise TactileSettingsError(
                "tactile settings directory must be a real directory"
            )

        try:
            current = self.path.lstat()
        except FileNotFoundError:
            current = None
        except OSError as exc:
            raise TactileSettingsError(
                "tactile settings target could not be inspected"
            ) from exc
        if current is not None and (
            stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode)
        ):
            raise TactileSettingsError(
                "tactile settings target must be a regular file"
            )

        descriptor: int | None = None
        temporary: str | None = None
        try:
            descriptor, temporary = tempfile.mkstemp(
                prefix=".tactile-settings-",
                suffix=".tmp",
                dir=parent,
            )
            try:
                os.fchmod(descriptor, 0o600)
            except (AttributeError, OSError):
                pass
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = None
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
            try:
                directory_fd = os.open(
                    parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                )
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as exc:
            raise TactileSettingsError(
                "tactile settings could not be saved atomically"
            ) from exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    @staticmethod
    def _decode(payload: object) -> TactileSettings:
        if type(payload) is not dict:
            raise TactileSettingsError("tactile settings root must be an object")
        expected = {
            "schema_version",
            "default_profile_id",
            "reconnect_enabled",
            "device_profiles",
        }
        if set(payload) != expected:
            raise TactileSettingsError("tactile settings fields are invalid")
        if payload["schema_version"] != SCHEMA_VERSION:
            raise TactileSettingsError("unsupported tactile settings schema")
        default_profile_id = payload["default_profile_id"]
        if default_profile_id is not None and type(default_profile_id) is not str:
            raise TactileSettingsError("default tactile profile id is invalid")
        reconnect_enabled = payload["reconnect_enabled"]
        if type(reconnect_enabled) is not bool:
            raise TactileSettingsError("reconnect_enabled must be boolean")
        rows = payload["device_profiles"]
        if type(rows) is not list or len(rows) > MAX_DEVICES:
            raise TactileSettingsError("device profile settings are invalid")
        pairs: list[tuple[str, str]] = []
        for row in rows:
            if type(row) is not dict or set(row) != {"device_id", "profile_id"}:
                raise TactileSettingsError("device profile entry is invalid")
            if (
                type(row["device_id"]) is not str
                or type(row["profile_id"]) is not str
            ):
                raise TactileSettingsError("device profile entry values are invalid")
            pairs.append((row["device_id"], row["profile_id"]))
        return TactileSettings(
            default_profile_id=default_profile_id,
            reconnect_enabled=reconnect_enabled,
            device_profiles=tuple(pairs),
        )


@dataclass(frozen=True, slots=True)
class TactileConnection:
    device_id: str
    profile_id: str
    capabilities: TactileDeviceCapabilities
    generation: int


@dataclass(frozen=True, slots=True)
class TactileInputEvent:
    device_id: str
    generation: int
    kind: TactileInputKind
    row: int | None = None
    column: int | None = None
    button: str | None = None

    def __post_init__(self) -> None:
        _validate_device_id(self.device_id)
        if type(self.generation) is not int or self.generation <= 0:
            raise TactileInputError("tactile input generation must be positive")
        if type(self.kind) is not TactileInputKind:
            raise TactileInputError("tactile input kind is invalid")
        if self.kind in {TactileInputKind.ROUTING, TactileInputKind.TOUCH}:
            if (
                type(self.row) is not int
                or type(self.column) is not int
                or self.button is not None
            ):
                raise TactileInputError(
                    "routing/touch input requires row and column only"
                )
        else:
            if (
                self.row is not None
                or self.column is not None
                or type(self.button) is not str
            ):
                raise TactileInputError(
                    "button input requires a button name only"
                )
            _validate_button_name(self.button)

    @classmethod
    def routing(
        cls, device_id: str, generation: int, row: int, column: int
    ) -> "TactileInputEvent":
        return cls(
            device_id,
            generation,
            TactileInputKind.ROUTING,
            row=row,
            column=column,
        )

    @classmethod
    def touch(
        cls, device_id: str, generation: int, row: int, column: int
    ) -> "TactileInputEvent":
        return cls(
            device_id,
            generation,
            TactileInputKind.TOUCH,
            row=row,
            column=column,
        )

    @classmethod
    def button_press(
        cls, device_id: str, generation: int, button: str
    ) -> "TactileInputEvent":
        return cls(
            device_id,
            generation,
            TactileInputKind.BUTTON,
            button=button,
        )


@dataclass(frozen=True, slots=True)
class TactileInputResult:
    device_id: str
    profile_id: str
    kind: TactileInputKind
    square: str | None
    dispatched_actions: tuple[str, ...]


_SAFE_BUTTON_ACTIONS = frozenset(
    {
        "board.current",
        "board.read_fen",
        "board.last_captured",
        "board.last_move",
        "board.my_clock",
        "board.opponent_clock",
        "board.legal_moves",
        "board.captures",
        "board.surroundings",
        "board.attackers",
        "board.defenders",
        "board.material",
        "board.evaluation",
        "board.best_move",
        "history.previous",
        "history.next",
    }
)
_SQUARE_NAVIGATION_ACTIONS = frozenset(
    {
        *(f"board.file_{index}" for index in range(1, 9)),
        *(f"board.rank_{index}" for index in range(1, 9)),
        "board.current",
    }
)
_SAFE_ACTIONS = _SAFE_BUTTON_ACTIONS | _SQUARE_NAVIGATION_ACTIONS


class TactileInputController:
    """Translate tactile events into fail-closed canonical application commands."""

    def __init__(
        self,
        profiles: TactileProfileRegistry,
        *,
        action_registry: ActionRegistryPort,
        dispatch: Callable[[str, Mapping[str, object]], object],
        settings_store: TactileDeviceSettingsStore,
    ) -> None:
        if not isinstance(profiles, TactileProfileRegistry):
            raise TypeError("profiles must be TactileProfileRegistry")
        if not callable(getattr(action_registry, "definition", None)):
            raise TypeError(
                "action_registry must expose definition(action_id)"
            )
        if not callable(dispatch):
            raise TypeError("dispatch must be callable")
        if not isinstance(settings_store, TactileDeviceSettingsStore):
            raise TypeError(
                "settings_store must be TactileDeviceSettingsStore"
            )
        self._profiles = profiles
        self._action_registry = action_registry
        self._dispatch = dispatch
        self._store = settings_store
        self._settings = settings_store.load()
        self._connections: dict[str, TactileConnection] = {}
        self._generation: dict[str, int] = {}
        self._validate_profile_actions()
        self._validate_saved_profile_ids()

    @property
    def settings(self) -> TactileSettings:
        return self._settings

    def connection(self, device_id: str) -> TactileConnection | None:
        _validate_device_id(device_id)
        return self._connections.get(device_id)

    def set_reconnect_enabled(self, enabled: bool) -> None:
        candidate = self._settings.with_reconnect_enabled(enabled)
        self._store.save(candidate)
        self._settings = candidate

    def set_default_profile(self, profile_id: str | None) -> None:
        if profile_id is not None:
            self._profiles.get(profile_id)
        candidate = self._settings.with_default_profile(profile_id)
        self._store.save(candidate)
        self._settings = candidate

    def connect(
        self,
        device_id: str,
        capabilities: TactileDeviceCapabilities,
        *,
        profile_id: str | None = None,
        remember: bool = True,
    ) -> TactileConnection:
        _validate_device_id(device_id)
        if not isinstance(capabilities, TactileDeviceCapabilities):
            raise TypeError(
                "capabilities must be TactileDeviceCapabilities"
            )
        if type(remember) is not bool:
            raise TypeError("remember must be boolean")
        profile = self._select_profile(
            device_id, capabilities, profile_id
        )
        generation = self._generation.get(device_id, 0) + 1
        connection = TactileConnection(
            device_id,
            profile.profile_id,
            capabilities,
            generation,
        )
        if remember:
            candidate = self._settings.with_device_profile(
                device_id, profile.profile_id
            )
            self._store.save(candidate)
            self._settings = candidate
        self._generation[device_id] = generation
        self._connections[device_id] = connection
        return connection

    def reconnect(
        self,
        device_id: str,
        capabilities: TactileDeviceCapabilities,
    ) -> TactileConnection | None:
        _validate_device_id(device_id)
        if not self._settings.reconnect_enabled:
            return None
        profile_id = self._settings.profile_for(device_id)
        if profile_id is None:
            return None
        profile = self._profiles.get(profile_id)
        if not profile.compatible_with(capabilities):
            return None
        return self.connect(
            device_id,
            capabilities,
            profile_id=profile_id,
            remember=False,
        )

    def disconnect(self, device_id: str) -> None:
        _validate_device_id(device_id)
        self._connections.pop(device_id, None)

    def set_connected_profile(
        self,
        device_id: str,
        profile_id: str,
        *,
        remember: bool = True,
    ) -> TactileConnection:
        current = self.connection(device_id)
        if current is None:
            raise TactileInputError("tactile device is not connected")
        return self.connect(
            device_id,
            current.capabilities,
            profile_id=profile_id,
            remember=remember,
        )

    def handle(self, event: TactileInputEvent) -> TactileInputResult:
        if not isinstance(event, TactileInputEvent):
            raise TypeError("event must be TactileInputEvent")
        connection = self._connections.get(event.device_id)
        if connection is None:
            raise TactileInputError("tactile device is not connected")
        if event.generation != connection.generation:
            raise TactileInputError("stale tactile input generation")
        profile = self._profiles.get(connection.profile_id)

        if event.kind is TactileInputKind.ROUTING:
            if (
                not connection.capabilities.routing
                or not profile.routing_enabled
            ):
                raise TactileInputError(
                    "routing input is not supported by this device profile"
                )
            square = profile.square_for_cell(
                event.row, event.column  # type: ignore[arg-type]
            )
            if square is None:
                raise TactileInputError(
                    "routing cell is outside the chess board layout"
                )
            actions = self._dispatch_square_navigation(square)
            return TactileInputResult(
                event.device_id,
                profile.profile_id,
                event.kind,
                square,
                actions,
            )

        if event.kind is TactileInputKind.TOUCH:
            if (
                not connection.capabilities.touch
                or not profile.touch_enabled
            ):
                raise TactileInputError(
                    "touch input is not supported by this device profile"
                )
            square = profile.square_for_cell(
                event.row, event.column  # type: ignore[arg-type]
            )
            if square is None:
                raise TactileInputError(
                    "touch cell is outside the chess board layout"
                )
            actions = self._dispatch_square_navigation(square)
            return TactileInputResult(
                event.device_id,
                profile.profile_id,
                event.kind,
                square,
                actions,
            )

        action_id = profile.button_map.get(event.button or "")
        if action_id is None:
            raise TactileInputError("tactile button is not mapped")
        self._dispatch_safe(action_id, {})
        return TactileInputResult(
            event.device_id,
            profile.profile_id,
            event.kind,
            None,
            (action_id,),
        )

    def _dispatch_square_navigation(self, square: str) -> tuple[str, ...]:
        file_index = ord(square[0]) - ord("a") + 1
        rank = int(square[1])
        actions = (
            f"board.file_{file_index}",
            f"board.rank_{rank}",
            "board.current",
        )
        for action_id in actions:
            self._dispatch_safe(action_id, {})
        return actions

    def _dispatch_safe(
        self, action_id: str, payload: Mapping[str, object]
    ) -> object:
        if action_id not in _SAFE_ACTIONS:
            raise TactileInputError(
                "tactile profile attempted an unsafe application command"
            )
        try:
            self._action_registry.definition(action_id)
        except Exception as exc:
            raise TactileInputError(
                "tactile application command is unavailable"
            ) from exc
        return self._dispatch(action_id, dict(payload))

    def _validate_profile_actions(self) -> None:
        for profile in self._profiles.profiles():
            for _button, action_id in profile.button_actions:
                if action_id not in _SAFE_BUTTON_ACTIONS:
                    raise TactileInputError(
                        "tactile button mapping is not read/navigation safe"
                    )
                try:
                    self._action_registry.definition(action_id)
                except Exception as exc:
                    raise TactileInputError(
                        "tactile button mapping references an unknown command"
                    ) from exc
        for action_id in _SQUARE_NAVIGATION_ACTIONS:
            try:
                self._action_registry.definition(action_id)
            except Exception as exc:
                raise TactileInputError(
                    "canonical board navigation commands are unavailable"
                ) from exc

    def _validate_saved_profile_ids(self) -> None:
        if self._settings.default_profile_id is not None:
            self._profiles.get(self._settings.default_profile_id)
        for _device_id, profile_id in self._settings.device_profiles:
            self._profiles.get(profile_id)

    def _select_profile(
        self,
        device_id: str,
        capabilities: TactileDeviceCapabilities,
        requested: str | None,
    ) -> TactileDeviceProfile:
        candidates: list[str] = []
        if requested is not None:
            candidates.append(requested)
        remembered = self._settings.profile_for(device_id)
        if remembered is not None and remembered not in candidates:
            candidates.append(remembered)
        default = self._settings.default_profile_id
        if default is not None and default not in candidates:
            candidates.append(default)
        for profile_id in candidates:
            profile = self._profiles.get(profile_id)
            if profile.compatible_with(capabilities):
                return profile
            if requested == profile_id:
                raise TactileInputError(
                    "requested tactile profile is incompatible with device capabilities"
                )
        fallback = self._profiles.first_compatible(capabilities)
        if fallback is None:
            raise TactileInputError(
                "no tactile device profile matches device capabilities"
            )
        return fallback


def default_tactile_profiles() -> tuple[TactileDeviceProfile, ...]:
    """Vendor-neutral profiles; hardware adapters may add vendor layouts."""
    common_buttons = (
        ("current", "board.current"),
        ("last", "board.last_move"),
        ("moves", "board.legal_moves"),
        ("fen", "board.read_fen"),
    )
    return (
        TactileDeviceProfile(
            "generic-8x8-white",
            "Generic 8x8 board, White at bottom",
            rows=8,
            columns=8,
            orientation=TactileOrientation.WHITE_BOTTOM,
        ),
        TactileDeviceProfile(
            "generic-8x8-black",
            "Generic 8x8 board, Black at bottom",
            rows=8,
            columns=8,
            orientation=TactileOrientation.BLACK_BOTTOM,
        ),
        TactileDeviceProfile(
            "generic-8x16-left",
            "Generic 8x16 layout, board on left",
            rows=8,
            columns=16,
            board_left=0,
            orientation=TactileOrientation.WHITE_BOTTOM,
        ),
        TactileDeviceProfile(
            "generic-8x12-controls",
            "Generic 8x12 board with four named controls",
            rows=8,
            columns=12,
            board_left=0,
            orientation=TactileOrientation.WHITE_BOTTOM,
            button_actions=common_buttons,
        ),
    )


def build_default_tactile_input_controller(
    *,
    settings_path: str | Path,
    action_registry: ActionRegistryPort,
    dispatch: Callable[[str, Mapping[str, object]], object],
) -> TactileInputController:
    return TactileInputController(
        TactileProfileRegistry(default_tactile_profiles()),
        action_registry=action_registry,
        dispatch=dispatch,
        settings_store=TactileDeviceSettingsStore(settings_path),
    )


def _validate_profile_id(value: object) -> None:
    if type(value) is not str or not _ID_RE.fullmatch(value):
        raise TactileInputError("tactile profile id is invalid")


def _validate_device_id(value: object) -> None:
    if type(value) is not str or not value or len(value) > _DEVICE_ID_MAX:
        raise TactileInputError("tactile device id is invalid")
    if value != value.strip() or any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in value
    ):
        raise TactileInputError(
            "tactile device id contains unsafe characters"
        )


def _validate_button_name(value: object) -> None:
    if type(value) is not str or not _ID_RE.fullmatch(value):
        raise TactileInputError("tactile button name is invalid")


def _validate_action_id(value: object) -> None:
    if type(value) is not str or not _ID_RE.fullmatch(value):
        raise TactileInputError("tactile action id is invalid")
