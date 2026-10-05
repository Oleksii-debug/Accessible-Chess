from __future__ import annotations

from acs.webview2_accessibility import (
    FORCE_RENDERER_ACCESSIBILITY,
    WEBVIEW2_BROWSER_ARGUMENTS_ENV,
    enable_webview2_renderer_accessibility,
)


def test_separated_remote_debug_feature_is_removed_without_dropping_benign_features() -> None:
    env = {
        WEBVIEW2_BROWSER_ARGUMENTS_ENV: (
            "--enable-features msEdgeDevToolsWDPRemoteDebugging "
            "--enable-features UseSkiaRenderer --foo=bar"
        )
    }

    sanitized = enable_webview2_renderer_accessibility(env)

    assert "msEdgeDevToolsWDPRemoteDebugging" not in sanitized
    assert "--enable-features UseSkiaRenderer" in sanitized
    assert "--foo=bar" in sanitized
    assert sanitized.count(FORCE_RENDERER_ACCESSIBILITY) == 1
    assert env[WEBVIEW2_BROWSER_ARGUMENTS_ENV] == sanitized


def test_quoted_separated_remote_debug_feature_is_removed() -> None:
    env = {
        WEBVIEW2_BROWSER_ARGUMENTS_ENV: (
            '--enable-features "msEdgeDevToolsWDPRemoteDebugging" --foo=bar'
        )
    }

    sanitized = enable_webview2_renderer_accessibility(env)

    assert "msEdgeDevToolsWDPRemoteDebugging" not in sanitized
    assert "--foo=bar" in sanitized
    assert FORCE_RENDERER_ACCESSIBILITY in sanitized
