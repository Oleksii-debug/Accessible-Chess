# Adapted from Oleksii-debug/Nika-Core@6df8b80b7a248f1559a0ff96f74efa2d2c47ad14
# Donor path: src/nika_core/media/files.py
# Integrated into Accessible Chess as a first-party cross-repository reuse.

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .media_errors import MediaError, MediaErrorCode
from .media_hashing import sha256_file
from .pinned_directory import pinned_real_directory


@dataclass(frozen=True, slots=True)
class PromotedFile:
    path: Path
    sha256: str
    size_bytes: int


def promote_partial_file(
    partial_path: Path,
    final_path: Path,
    *,
    allowed_root: Path,
    expected_sha256: str | None = None,
    max_bytes: int | None = None,
) -> PromotedFile:
    """Validate and atomically publish one media artifact inside a pinned root.

    The original Nika implementation already bounded paths and refused overwrite.
    Accessible Chess additionally pins the allowed-root directory identity using
    the 12-6-ai recovery primitive so a pathname swap cannot redirect the final
    publication after validation.
    """
    root = allowed_root.resolve(strict=True)
    partial_visible = partial_path.resolve(strict=True)
    final_parent_visible = final_path.parent.resolve(strict=True)
    try:
        partial_rel = partial_visible.relative_to(root)
        final_parent_rel = final_parent_visible.relative_to(root)
    except ValueError as exc:
        raise MediaError(
            MediaErrorCode.PATH_ESCAPE,
            "media output escapes the allowed root",
        ) from exc

    with pinned_real_directory(root) as pinned:
        pinned.verify_binding()
        partial = pinned.path / partial_rel
        final_parent = pinned.path / final_parent_rel
        final = final_parent / final_path.name

        if partial.suffix != ".partial":
            raise ValueError("partial media output must use the .partial suffix")
        if final.exists() or final.is_symlink():
            raise FileExistsError(
                f"refusing to overwrite existing media output: {final_path.name}"
            )
        checksum = sha256_file(partial, max_bytes=max_bytes)
        if (
            expected_sha256 is not None
            and checksum != expected_sha256.lower()
        ):
            raise MediaError(
                MediaErrorCode.CHECKSUM_MISMATCH,
                "media output checksum did not match",
            )
        size = partial.stat().st_size
        pinned.verify_binding()
        if final.exists() or final.is_symlink():
            raise FileExistsError(
                f"media output appeared before publication: {final_path.name}"
            )
        os.replace(partial, final)
        pinned.verify_binding()

    return PromotedFile(
        path=final_path,
        sha256=checksum,
        size_bytes=size,
    )

