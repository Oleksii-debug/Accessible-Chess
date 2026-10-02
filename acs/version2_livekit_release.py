from __future__ import annotations

"""Shipping LiveKit WebView resource composition for the Version 2 final product.

The pinned browser SDK is materialized by the existing #1079 package authority.
This module owns no media, classroom, chess, token, or provider semantics. It
only makes the already-packaged SDK and the canonical provider-neutral browser
adapter reachable through the existing final-product resource injection seam.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import version2_education_mutation_release as _education_release
from . import version2_release_ui as _release_ui
from . import version2_upgrade_status_release as _status_release


LIVEKIT_SDK_RESOURCE_LABEL = "LiveKit browser SDK"
LIVEKIT_ADAPTER_RESOURCE_LABEL = "Accessible Chess LiveKit classroom media adapter"
LIVEKIT_SDK_RELATIVE_PATH = Path("web") / "vendor" / "livekit" / "livekit-client.umd.js"
LIVEKIT_ADAPTER_RELATIVE_PATH = Path("web") / "livekit_classroom_media.js"

# Capture the inherited resource authority once so temporary late binding below
# cannot recurse into itself.
_BASE_RESOURCE_SOURCES = _education_release.final_product_resource_sources


def _required_text(path: Path, label: str) -> str:
    try:
        if not path.is_file():
            raise RuntimeError(f"{label} not found in packaged resources.")
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        # Do not attach the filesystem exception: its traceback may disclose an
        # absolute Windows profile/build path. The label is sufficient for
        # operator diagnosis and remains stable across source/package layouts.
        raise RuntimeError(
            f"{label} could not be read from packaged resources."
        ) from None
    if not source.strip():
        raise RuntimeError(f"{label} is empty in packaged resources.")
    return source


def livekit_resource_sources() -> tuple[tuple[str, str], ...]:
    """Return SDK first, then adapter, from the current packaged asset root."""

    root = _release_ui._asset_root()
    sdk = _required_text(root / LIVEKIT_SDK_RELATIVE_PATH, LIVEKIT_SDK_RESOURCE_LABEL)
    adapter = _required_text(
        root / LIVEKIT_ADAPTER_RELATIVE_PATH,
        LIVEKIT_ADAPTER_RESOURCE_LABEL,
    )
    return (
        (LIVEKIT_SDK_RESOURCE_LABEL, sdk),
        (LIVEKIT_ADAPTER_RESOURCE_LABEL, adapter),
    )


def final_product_resource_sources() -> tuple[tuple[str, str], ...]:
    """Extend the accepted final-product sources with exact LiveKit runtime order."""

    inherited = tuple(_BASE_RESOURCE_SOURCES())
    labels = tuple(label for label, _source in inherited)
    if (
        LIVEKIT_SDK_RESOURCE_LABEL in labels
        or LIVEKIT_ADAPTER_RESOURCE_LABEL in labels
    ):
        raise RuntimeError("LiveKit WebView resources are already registered.")
    return inherited + livekit_resource_sources()


@contextmanager
def _livekit_resource_bindings() -> Iterator[None]:
    """Temporarily make the inherited release root consume the extended sources."""

    previous = _education_release.final_product_resource_sources
    _education_release.final_product_resource_sources = final_product_resource_sources
    try:
        yield
    finally:
        _education_release.final_product_resource_sources = previous


def create_version2_release_application(*args: Any, **kwargs: Any):
    """Compose the same final product while retaining LiveKit resource reachability."""

    defer_ui = kwargs.get("defer_ui", False) is True
    with _livekit_resource_bindings():
        composed = _status_release.create_version2_release_application(*args, **kwargs)

    if not defer_ui:
        return composed

    api, application_factory, runtime, native_runtime_factory = composed
    if not callable(application_factory):
        raise TypeError("deferred Version 2 application factory must be callable")

    def build_livekit_application():
        with _livekit_resource_bindings():
            return application_factory()

    return api, build_livekit_application, runtime, native_runtime_factory


def main() -> None:
    """Run the existing shipping UI with LiveKit resources bound for UI lifetime."""

    with _livekit_resource_bindings():
        _status_release.main()


__all__ = [
    "LIVEKIT_ADAPTER_RELATIVE_PATH",
    "LIVEKIT_ADAPTER_RESOURCE_LABEL",
    "LIVEKIT_SDK_RELATIVE_PATH",
    "LIVEKIT_SDK_RESOURCE_LABEL",
    "create_version2_release_application",
    "final_product_resource_sources",
    "livekit_resource_sources",
    "main",
]
