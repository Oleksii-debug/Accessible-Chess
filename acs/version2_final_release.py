from __future__ import annotations

"""Scoped final-product release composition over the accepted Version 2 root.

The final product needs the wider Teacher/Classes action profile, native menu,
language synchronization, and packaged WebView resources while it is being
composed or run.  Those seams are process-global in the accepted release root,
so importing this module must not permanently replace narrower Version 2 owners:
large in-process regression suites and tooling legitimately use both profiles.
"""

from contextlib import contextmanager
from typing import Any, Callable, Iterator

from . import version2_release_app as _release_app
from . import version2_release_ui as _release_ui
from .agent_execution_host import AgentOwnerThreadCall, bind_agent_runtime
from .full_product_ui_shell import UILanguage
from .universal_chess_agent import UniversalChessAgentRuntime
from .version2_final_product_application import Version2FinalProductApplication
from .version2_final_product_profile import (
    FINAL_PRODUCT_ACTION_IDS,
    FinalProductNativeMenuController,
)


def _final_product_resource_sources() -> tuple[tuple[str, str], ...]:
    root = _release_ui._asset_root() / "web"
    resources = (
        ("Stage 1 WebView bootstrap", root / "stage1_release_bootstrap.js"),
        ("Stage 1 board action bridge", root / "stage1_board_actions.js"),
        ("V2 PGN surface", root / "full_product_pgn.js"),
        ("V2 Library surface", root / "full_product_library.js"),
        ("V2 Books surface", root / "full_product_books_training.js"),
        ("V2 Teacher surface", root / "full_product_teacher.js"),
        ("V2 Education surface", root / "full_product_education.js"),
        ("V2 Agent surface", root / "full_product_agent.js"),
        ("V2 final-product bootstrap", root / "version2_final_product_bootstrap.js"),
        # The final bootstrap creates #v2-workspace synchronously, then starts an
        # asynchronous snapshot refresh. Load P0 after that DOM owner exists so
        # selection retention observes the real workspace, while surface wrappers
        # still bind before a user can interact with the composed routes.
        ("P0 event-aware accessibility runtime", root / "p0_accessibility_runtime.js"),
    )
    output: list[tuple[str, str]] = []
    for label, path in resources:
        if not path.exists():
            raise RuntimeError(f"{label} not found in packaged resources.")
        output.append((label, path.read_text(encoding="utf-8")))
    return tuple(output)


def _composed_language_sync(
    base_sync: Callable[[Any, UILanguage], None],
) -> Callable[[Any, UILanguage], None]:
    def sync(application: Any, language: UILanguage) -> None:
        base_sync(application, language)
        composed_sync = getattr(application, "sync_composed_surfaces_language", None)
        if callable(composed_sync):
            composed_sync(language)

    return sync


@contextmanager
def _final_product_bindings() -> Iterator[Callable[[Any, UILanguage], None]]:
    """Install final-product release seams only for one bounded composition lifetime."""

    api_type = _release_ui.Version2ReleaseAccessibleChessAPI
    previous_application = _release_app.Version2Application
    previous_action_ids = _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS
    previous_controller = _release_ui.Version2NativeMenuController
    previous_sync_descriptor = api_type.__dict__["_sync_version2_language"]
    previous_sync = getattr(api_type, "_sync_version2_language")
    previous_resources = _release_ui._resource_sources

    _release_app.Version2Application = Version2FinalProductApplication
    _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS = FINAL_PRODUCT_ACTION_IDS
    _release_ui.Version2NativeMenuController = FinalProductNativeMenuController
    setattr(
        api_type,
        "_sync_version2_language",
        staticmethod(_composed_language_sync(previous_sync)),
    )
    _release_ui._resource_sources = _final_product_resource_sources
    try:
        yield previous_sync
    finally:
        _release_ui._resource_sources = previous_resources
        setattr(api_type, "_sync_version2_language", previous_sync_descriptor)
        _release_ui.Version2NativeMenuController = previous_controller
        _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS = previous_action_ids
        _release_app.Version2Application = previous_application


def _bind_api_language_sync(
    api: Any,
    base_sync: Callable[[Any, UILanguage], None],
) -> None:
    setattr(api, "_sync_version2_language", _composed_language_sync(base_sync))


def _bind_agent_execution(
    api: Any,
    application: Version2FinalProductApplication,
    factory: Callable[[Any, Version2FinalProductApplication, AgentOwnerThreadCall], object] | None,
) -> None:
    """Bind an explicitly configured model/runtime without inventing a provider."""

    if factory is None:
        return
    owner_call = AgentOwnerThreadCall(api._invoke_ui)
    runtime = factory(api, application, owner_call)
    if type(runtime) is not UniversalChessAgentRuntime:
        raise TypeError("agent_runtime_factory must return UniversalChessAgentRuntime")
    bind_agent_runtime(application, runtime)


def create_version2_release_application(*args: Any, **kwargs: Any):
    """Create the final product and optionally bind its canonical Agent runtime.

    No model provider is guessed from environment or credentials. A release host
    that has an approved provider supplies agent_runtime_factory; otherwise the
    Agent route remains reachable but explicitly unavailable.
    """

    agent_runtime_factory = kwargs.pop("agent_runtime_factory", None)
    if agent_runtime_factory is not None and not callable(agent_runtime_factory):
        raise TypeError("agent_runtime_factory must be callable or None")

    defer_ui = kwargs.get("defer_ui", False) is True
    with _final_product_bindings() as base_sync:
        composed = _release_app.create_version2_release_application(*args, **kwargs)
        api = composed[0]
        _bind_api_language_sync(api, base_sync)

    if not defer_ui:
        api, application, runtime, native_runtime_factory = composed
        try:
            _bind_agent_execution(api, application, agent_runtime_factory)
        except BaseException:
            try:
                application.shutdown()
            except BaseException:
                pass
            try:
                runtime.close()
            except BaseException:
                pass
            raise
        return api, application, runtime, native_runtime_factory

    api, application_factory, runtime, native_runtime_factory = composed
    if not callable(application_factory):
        raise TypeError("deferred Version 2 application factory must be callable")

    def build_final_product_application():
        with _final_product_bindings():
            application = application_factory()
        try:
            _bind_agent_execution(api, application, agent_runtime_factory)
        except BaseException:
            try:
                application.shutdown()
            except BaseException:
                pass
            raise
        return application

    return api, build_final_product_application, runtime, native_runtime_factory


def main() -> None:
    # The accepted main() owns the complete synchronous native UI lifetime.
    # Keep final-product seams installed only for that lifetime and restore even
    # when startup or shutdown raises.
    with _final_product_bindings():
        _release_app.main()


__all__ = ["create_version2_release_application", "main"]
