from __future__ import annotations

"""Packaged WebView2 accessibility process boundary for Stage 1."""

import os
from collections.abc import MutableMapping

WEBVIEW2_BROWSER_ARGUMENTS_ENV = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
FORCE_RENDERER_ACCESSIBILITY = "--force-renderer-accessibility"


def enable_webview2_renderer_accessibility(
    environment: MutableMapping[str, str] | None = None,
) -> str:
    """Force Chromium renderer accessibility before WebView2 initialization.

    Raw Windows UI Automation clients do not necessarily advertise themselves
    to Chromium like a running assistive technology does.  WebView2 supports
    process-level additional browser arguments through
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS.  Preserve existing arguments and add
    the renderer-accessibility switch exactly once.
    """

    env = os.environ if environment is None else environment
    current = str(env.get(WEBVIEW2_BROWSER_ARGUMENTS_ENV, "")).strip()
    tokens = current.split()
    if not any(
        token == FORCE_RENDERER_ACCESSIBILITY
        or token.startswith(FORCE_RENDERER_ACCESSIBILITY + "=")
        for token in tokens
    ):
        current = (current + " " + FORCE_RENDERER_ACCESSIBILITY).strip()
        env[WEBVIEW2_BROWSER_ARGUMENTS_ENV] = current
    return str(env.get(WEBVIEW2_BROWSER_ARGUMENTS_ENV, current))
