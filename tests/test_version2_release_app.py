from __future__ import annotations

import unittest

from acs.version2_release_app import _install_host_confirmed_document


class _Application:
    def __init__(self) -> None:
        self.confirm_calls = 0
        self.installed = []

        def original_confirmation() -> bool:
            self.confirm_calls += 1
            return False

        self.confirm_document_replace = original_confirmation

    def set_document(self, session):
        if not self.confirm_document_replace():
            raise RuntimeError("replacement was not host-confirmed")
        self.installed.append(session)
        return session


class Version2ReleaseAppTests(unittest.TestCase):
    def test_trusted_host_confirmation_is_not_requested_twice(self) -> None:
        application = _Application()
        original = application.confirm_document_replace
        session = object()

        result = _install_host_confirmed_document(application, session)

        self.assertIs(result, session)
        self.assertEqual(application.installed, [session])
        self.assertEqual(application.confirm_calls, 0)
        self.assertIs(application.confirm_document_replace, original)

    def test_confirmation_callback_is_restored_after_install_failure(self) -> None:
        application = _Application()
        original = application.confirm_document_replace

        def failing_set_document(_session):
            self.assertTrue(application.confirm_document_replace())
            raise ValueError("synthetic install failure")

        application.set_document = failing_set_document
        with self.assertRaisesRegex(ValueError, "synthetic install failure"):
            _install_host_confirmed_document(application, object())

        self.assertIs(application.confirm_document_replace, original)
        self.assertEqual(application.confirm_calls, 0)


if __name__ == "__main__":
    unittest.main()
