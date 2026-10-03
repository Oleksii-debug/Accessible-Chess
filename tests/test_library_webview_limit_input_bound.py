from __future__ import annotations

import unittest

from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import UILanguage
from acs.library_webview_bridge import LibraryWebViewBridge
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchPage, GameSearchQuery


class _Service:
    def __init__(self) -> None:
        self.calls: list[GameSearchQuery] = []

    def search(self, query: GameSearchQuery) -> GameSearchPage:
        self.calls.append(query.normalized())
        return GameSearchPage(items=(), next_after_game_id=None, has_more=False)


class LibraryWebViewLimitInputBoundTests(unittest.TestCase):
    def _build(self):
        service = _Service()
        presenter = LibraryPresenter(service, language=UILanguage.EN)
        projection = LibraryWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            language=UILanguage.EN,
        )
        return service, LibraryWebViewBridge(projection)

    def test_oversized_decimal_limit_is_rejected_before_integer_conversion_path_reaches_search(self) -> None:
        service, bridge = self._build()
        oversized = "9" * 100_000

        event = bridge.dispatch("library.search", {"limit": oversized})

        self.assertEqual("error", event.kind)
        self.assertEqual([], service.calls)
        self.assertNotIn("999999", repr(event.payload))

    def test_overlong_zero_padded_small_limit_is_still_rejected_by_input_bound(self) -> None:
        service, bridge = self._build()

        event = bridge.dispatch(
            "library.search",
            {"limit": "00000000000000000025"},
        )

        self.assertEqual("error", event.kind)
        self.assertEqual([], service.calls)

    def test_bounded_ascii_decimal_limit_remains_supported(self) -> None:
        service, bridge = self._build()

        event = bridge.dispatch("library.search", {"limit": "0000000000000000200"})

        self.assertEqual("render", event.kind)
        self.assertEqual(1, len(service.calls))
        self.assertEqual(200, service.calls[0].limit)

    def test_noncanonical_limit_types_fail_before_backend_search(self) -> None:
        for value in (True, 1.0, "-1", "+25", "２５", object()):
            with self.subTest(value=repr(value)):
                service, bridge = self._build()

                event = bridge.dispatch("library.search", {"limit": value})

                self.assertEqual("error", event.kind)
                self.assertEqual([], service.calls)


if __name__ == "__main__":
    unittest.main()
