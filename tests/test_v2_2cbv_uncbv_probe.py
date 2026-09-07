from __future__ import annotations

import unittest

from scripts.v2_2cbv_uncbv_probe import _suffix_histogram


class TwoCbvUncbvProbeTests(unittest.TestCase):
    def test_suffix_histogram_exposes_topology_without_entry_names(self) -> None:
        result = _suffix_histogram(
            [
                "Tournament.2cbh",
                "Tournament.2cbg",
                "folder/Tournament.2cba",
                "Tournament.2cbg",
                "README",
                "",
            ]
        )
        self.assertEqual(
            result,
            {".2cba": 1, ".2cbg": 2, ".2cbh": 1, "<none>": 1},
        )
        self.assertNotIn("Tournament", repr(result))
        self.assertNotIn("folder", repr(result))

    def test_windows_separator_is_normalized_for_suffix_only_evidence(self) -> None:
        self.assertEqual(
            _suffix_histogram([r"nested\Database.2CBH", r"nested\Database.2LGD"]),
            {".2cbh": 1, ".2lgd": 1},
        )


if __name__ == "__main__":
    unittest.main()
