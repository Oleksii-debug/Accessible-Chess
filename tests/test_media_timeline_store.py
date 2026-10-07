from __future__ import annotations

from pathlib import Path

import pytest

from acs.chesscore import Board
from acs.media_foundation import (
    MediaContractError,
    MediaPositionBinding,
    MediaPositionTimeline,
)
from acs.media_timeline_store import MediaTimelineStore


AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


def _timeline(end_ms: int = 2000) -> MediaPositionTimeline:
    return MediaPositionTimeline(
        (
            MediaPositionBinding(0, 1000, Board.START),
            MediaPositionBinding(1000, end_ms, AFTER_E4, tree_path=(0,)),
        )
    )


def test_timeline_payload_round_trip_preserves_exact_position_identity() -> None:
    original = _timeline()
    restored = MediaPositionTimeline.from_payload(original.to_payload())
    assert restored.bindings == original.bindings
    assert restored.restore_fen(1500) == AFTER_E4


def test_timeline_store_survives_restart_and_selects_latest_revision(tmp_path: Path) -> None:
    root = tmp_path / "media-timelines"
    store = MediaTimelineStore(root)
    first = store.save(session_id="video-1", revision=1, timeline=_timeline())
    second = store.save(
        session_id="video-1",
        revision=2,
        timeline=_timeline(3000),
    )

    assert first.path.exists()
    assert second.path.exists()
    restarted = MediaTimelineStore(root)
    latest = restarted.latest("video-1")
    assert latest is not None
    assert latest.revision == 2
    assert latest.timeline.restore_fen(2500) == AFTER_E4


def test_timeline_store_rejects_non_monotonic_revision(tmp_path: Path) -> None:
    store = MediaTimelineStore(tmp_path / "timelines")
    store.save(session_id="video-1", revision=1, timeline=_timeline())
    with pytest.raises(MediaContractError, match="advance"):
        store.save(session_id="video-1", revision=1, timeline=_timeline())


def test_timeline_store_skips_corrupt_newer_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "timelines"
    store = MediaTimelineStore(root)
    store.save(session_id="video-1", revision=1, timeline=_timeline())
    key = store._session_key("video-1")
    corrupt = root / f"timeline-{key}-{999:012d}-{'0' * 64}.json"
    corrupt.write_text('{"not":"a valid envelope"}', encoding="utf-8")

    latest = MediaTimelineStore(root).latest("video-1")
    assert latest is not None
    assert latest.revision == 1


def test_timeline_store_does_not_follow_snapshot_symlink(tmp_path: Path) -> None:
    root = tmp_path / "timelines"
    root.mkdir()
    store = MediaTimelineStore(root)
    key = store._session_key("video-1")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = root / f"timeline-{key}-{999:012d}-{'0' * 64}.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable for this test account")

    assert store.latest("video-1") is None
    assert outside.read_text(encoding="utf-8") == "{}"
