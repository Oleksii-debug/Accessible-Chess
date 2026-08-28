from __future__ import annotations

import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.version2_windows_file_workflows import Version2WindowsFileActionDelegate


class V2LibraryExportReachabilityAuditTests(unittest.TestCase):
    def test_advertised_library_export_has_a_trusted_windows_file_port(self) -> None:
        """Filesystem export must not be advertised without a trusted host destination seam."""

        registry = build_full_product_action_registry()
        registered = frozenset(item.action_id for item in registry.definitions())
        self.assertIn(
            "library.export",
            registered,
            "precondition: the V2 action authority must advertise Library export",
        )
        self.assertIn(
            "library.export",
            Version2WindowsFileActionDelegate.OWNED_ACTIONS,
            "Library export is advertised but has no trusted Windows file-workflow port; "
            "browser/native presentation must not invent or submit filesystem paths",
        )


if __name__ == "__main__":
    unittest.main()
