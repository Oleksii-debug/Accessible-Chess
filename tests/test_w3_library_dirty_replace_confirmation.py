from __future__ import annotations

import inspect
import unittest

from acs.version2_release_app import create_version2_release_application


class W3LibraryDirtyReplaceConfirmationEvidenceTests(unittest.TestCase):
    def test_production_composition_binds_trusted_dirty_replace_confirmation_for_library_open(self) -> None:
        """Library -> Open game must not be a dead end when the current PGN is dirty.

        Version2Application already owns a fail-closed ``confirm_document_replace``
        seam.  Native PGN Open is confirmed by the trusted Windows host before
        installation, but Library -> Open game calls ``set_document`` directly.
        The production composition therefore needs to bind the same owner-bound
        confirmation authority after the native owner exists, rather than leave
        the application's default ``lambda: not dirty`` in place forever.
        """

        source = inspect.getsource(create_version2_release_application)
        self.assertIn(
            "application.confirm_document_replace =",
            source,
            "production composition does not bind a trusted confirmation seam for Library -> Open game",
        )


if __name__ == "__main__":
    unittest.main()
