from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI
from tests.test_version2_release_ui import _Application


class _HostileContext:
    touched = False

    def __getattribute__(self, name):
        if name not in {"touched", "__class__"}:
            type(self).touched = True
            raise AssertionError("hostile context attribute hook must not execute")
        return super().__getattribute__(name)

    def __bool__(self):
        type(self).touched = True
        raise AssertionError("hostile context truth hook must not execute")

    def __str__(self):
        type(self).touched = True
        raise AssertionError("hostile context string hook must not execute")


class _HostileText(str):
    armed = False
    touched = False

    @classmethod
    def reset(cls):
        cls.armed = False
        cls.touched = False

    @classmethod
    def _touch(cls):
        if cls.armed:
            cls.touched = True
            raise AssertionError("hostile context text hook must not execute")

    def strip(self, *args, **kwargs):
        type(self)._touch()
        return super().strip(*args, **kwargs)

    def lower(self, *args, **kwargs):
        type(self)._touch()
        return super().lower(*args, **kwargs)

    def __hash__(self):
        type(self)._touch()
        return super().__hash__()

    def __eq__(self, other):
        type(self)._touch()
        return super().__eq__(other)


class Version2KeymapContextPassiveTests(unittest.TestCase):
    def make_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        api = Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json"
        )
        api.bind_version2_application(_Application())
        return api

    def test_context_helper_rejects_active_object_before_attribute_truth_or_string_hooks(self):
        _HostileContext.touched = False

        self.assertEqual(
            Version2ReleaseAccessibleChessAPI._keymap_context_name(_HostileContext()),
            "",
        )
        self.assertFalse(_HostileContext.touched)

    def test_context_helper_rejects_str_subclass_before_text_hooks(self):
        _HostileText.reset()
        context = _HostileText("board")
        _HostileText.armed = True

        self.assertEqual(
            Version2ReleaseAccessibleChessAPI._keymap_context_name(context),
            "",
        )
        self.assertFalse(_HostileText.touched)

    def test_public_binding_resolution_rejects_active_context_before_v2_precedence_hooks(self):
        api = self.make_api()
        _HostileContext.touched = False

        result = api.keymap_resolve_binding(_HostileContext(), "Ctrl+Alt+L")

        self.assertIsNone(result)
        self.assertFalse(_HostileContext.touched)

    def test_public_alias_resolution_rejects_active_text_context_before_hooks(self):
        api = self.make_api()
        _HostileText.reset()
        context = _HostileText("document")
        _HostileText.armed = True

        result = api.keymap_resolve_alias(context, "next-item")

        self.assertIsNone(result)
        self.assertFalse(_HostileText.touched)

    def test_exact_context_normalization_and_route_precedence_remain_unchanged(self):
        api = self.make_api()
        registry = api._version2().adapter.registry
        registry.set_binding("screen.library", "Ctrl+Alt+L", allow_warnings=True)

        self.assertEqual(api._keymap_context_name(" DOCUMENT "), "document")
        resolved = api.keymap_resolve_binding("document", "Ctrl+Alt+L")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "screen.library")
        self.assertEqual(resolved["context"], "global")


if __name__ == "__main__":
    unittest.main()
