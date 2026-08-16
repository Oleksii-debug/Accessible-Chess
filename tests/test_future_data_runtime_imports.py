import importlib
import unittest


class FutureDataRuntimeImportTests(unittest.TestCase):
    def test_vertical_slice_runtime_modules_import_from_exact_tracked_tree(self):
        for module_name in (
            "acs.gametree",
            "acs.pgn_semantics",
            "acs.game_references",
            "acs.pgn_workspace",
            "acs.pgn_collection",
            "acs.acsdb",
            "acs.acsdb_catalog",
            "acs.import_contract",
        ):
            module = importlib.import_module(module_name)
            self.assertEqual(module.__name__, module_name)


if __name__ == "__main__":
    unittest.main()
