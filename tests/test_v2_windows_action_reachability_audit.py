from __future__ import annotations

import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.version2_windows_file_workflows import Version2WindowsFileActionDelegate


class V2WindowsActionReachabilityAuditTests(unittest.TestCase):
    def test_trusted_file_ports_are_registered_in_canonical_action_authority(self) -> None:
        """A trusted-host port is not a usable V2/NVDA feature until the one action path can reach it."""

        registry = build_full_product_action_registry()
        registered = frozenset(item.action_id for item in registry.definitions())
        required = Version2WindowsFileActionDelegate.OWNED_ACTIONS

        self.assertTrue(
            required.issubset(registered),
            "trusted Windows file workflow ports are unreachable through the canonical ActionRegistry; "
            f"missing={sorted(required - registered)!r}",
        )


if __name__ == "__main__":
    unittest.main()
