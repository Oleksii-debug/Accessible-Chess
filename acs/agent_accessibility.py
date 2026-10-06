from __future__ import annotations

"""Screen-reader-friendly status rendering for Agent/Media surfaces.

Pattern adapted from:
Oleksii-debug/AutoTrade@main
mvp/autotrade_mvp/accessibility.py blob 046b151ce0f61d73718c1ca0b66c33cc6368ce04

Plain text is intentionally stable, copyable and free of visual-only state.
"""

from collections.abc import Mapping


def _value(mapping: Mapping[str, object], key: str, default: str = "Unavailable") -> str:
    value = mapping.get(key)
    return default if value is None else str(value)


def format_agent_status(status: Mapping[str, object]) -> str:
    state = str(status.get("state", "unknown"))
    lines = [
        "Accessible Chess agent status",
        f"State: {state}",
        f"Task: {_value(status, 'task_id')}",
        f"Provider: {_value(status, 'provider_id')}",
        f"Model: {_value(status, 'model')}",
        f"Current tool: {_value(status, 'tool_id')}",
        f"Steps: {_value(status, 'steps', '0')}",
    ]
    if status.get("cancelled") is True:
        lines.append("Cancellation: requested")
    error = status.get("error")
    if error:
        lines.append(f"Error: {error}")
    return "\n".join(lines)


def format_media_status(status: Mapping[str, object]) -> str:
    lines = [
        "Accessible Chess media status",
        f"Playback: {_value(status, 'playback_state', 'Unknown')}",
        f"Time: {_value(status, 'current_ms', '0')} milliseconds",
        f"Synchronization: {_value(status, 'reconciliation_status', 'Unknown')}",
        f"Position: {_value(status, 'position_id')}",
        f"Move: {_value(status, 'move_id')}",
    ]
    if status.get("analysis_detached") is True:
        lines.append("Analysis detached: yes")
        lines.append("Board mode: independent analysis; Restore Media Position is available")
    reason = status.get("reason")
    if reason:
        lines.append(f"Detail: {reason}")
    return "\n".join(lines)


__all__ = ["format_agent_status", "format_media_status"]
