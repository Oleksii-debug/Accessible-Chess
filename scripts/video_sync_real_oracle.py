#!/usr/bin/env python3
"""Real-video oracle for deterministic board/move synchronization.

This tool consumes user-supplied lawful MP4 files without adding them to Git.
It decodes the visible board with ffmpeg, ranks square changes, and accepts only
canonical legal moves from ``acs.chesscore.Board``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from acs.chesscore import Board


def _features(frame: np.ndarray, size: int = 360) -> list[np.ndarray]:
    square = size // 8
    features = []
    for rank in range(8):
        row = 7 - rank
        for file_index in range(8):
            features.append(frame[row * square + 4:(row + 1) * square - 4, file_index * square + 4:(file_index + 1) * square - 4].astype(np.int16))
    return features


def _changed_squares(board: Board, move) -> set[int]:
    changed = {move.frm, move.to}
    if move.castle:
        changed.update({6: (7, 5), 2: (0, 3), 62: (63, 61), 58: (56, 59)}[move.to])
    if move.en_passant:
        changed.add(move.to - 8 if move.to > move.frm else move.to + 8)
    return changed


def recognize(path: Path, *, start: float, duration: float, fps: int = 2, limit: int = 32) -> list[dict[str, object]]:
    size = 360
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(start), "-t", str(duration),
        "-i", str(path), "-vf", f"fps={fps},crop={size}:{size}:0:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    assert process.stdout is not None
    frame_bytes = size * size * 3
    board = Board()
    baseline = previous = None
    accepted: list[dict[str, object]] = []
    index = 0
    while len(accepted) < limit:
        raw = process.stdout.read(frame_bytes)
        if len(raw) != frame_bytes:
            break
        index += 1
        current = _features(np.frombuffer(raw, dtype=np.uint8).reshape(size, size, 3), size)
        if baseline is None:
            baseline = previous = current
            continue
        inter = np.array([np.abs(a - b).mean() for a, b in zip(current, previous)])
        previous = current
        if float(np.percentile(inter, 90)) > 4.0:
            continue
        difference = np.array([np.abs(a - b).mean() for a, b in zip(current, baseline)])
        order = np.argsort(difference)[::-1]
        if float(difference[order[1]]) < 8.0:
            continue
        changed_count = int((difference >= max(8.0, float(difference[order[0]]) * 0.28)).sum())
        if changed_count > 6:
            continue
        ranked = []
        for move in board.legal_moves():
            changed = _changed_squares(board, move)
            values = [float(difference[square]) for square in changed]
            cover = sum(square in order[:max(3, len(changed) + 1)] for square in changed)
            endpoints = sum(square in order[:4] for square in (move.frm, move.to))
            score = sum(values) / len(values) - 0.35 * float(difference[order[min(63, len(changed))]])
            ranked.append((cover, endpoints, score, move))
        cover, endpoints, score, move = max(ranked, key=lambda item: item[:3])
        if cover < 2 or endpoints < 2 or score <= 5.0:
            continue
        san = board.push(move)
        accepted.append({"timecode": round(start + index / fps, 1), "san": san, "confidence": round(max(0.0, min(1.0, (score - 5.0) / 35.0)), 3)})
        baseline = current
    process.terminate()
    process.wait(timeout=5)
    return accepted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--expect-prefix", default="")
    args = parser.parse_args()
    moves = recognize(args.video, start=args.start, duration=args.duration)
    expected = [item for item in args.expect_prefix.split(",") if item]
    actual = [item["san"] for item in moves[:len(expected)]]
    ok = args.video.is_file() and (not expected or actual == expected)
    digest = hashlib.sha256(args.video.read_bytes()).hexdigest()
    print(json.dumps({"ok": ok, "video": args.video.name, "sha256": digest, "recognized": moves, "expected_prefix": expected}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
