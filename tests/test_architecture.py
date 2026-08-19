import ast
from pathlib import Path
import unittest


# Presentation-neutral reusable modules.  Keep this list explicit so adding a
# new core/domain service requires an intentional architecture-gate decision.
CORE_MODULES = (
    'acs/squares.py',
    'acs/chesscore.py',
    'acs/board_service.py',
    'acs/position_editor.py',
    'acs/interaction_contracts.py',
    'acs/interaction_router.py',
    'acs/history.py',
    'acs/gametree.py',
    'acs/pgn.py',
    'acs/pgn_service.py',
    'acs/bookdocument.py',
    'acs/book_index.py',
    'acs/bookreader.py',
    'acs/training.py',
    'acs/game_lifecycle.py',
    'acs/clock_service.py',
    'acs/keybindings.py',
    'acs/notation.py',
    'acs/notation_registry.py',
    'acs/engine_ports.py',
    'acs/engine_play_service.py',
    'acs/engine_game_session.py',
    'acs/engine_registry.py',
    'acs/analysis_service.py',
    'acs/continuous_analysis.py',
    'acs/sound_dispatch.py',
    'acs/import_contract.py',
    'acs/import_registry.py',
    'acs/game_identity.py',
    'acs/duplicate_detection.py',
)

FORBIDDEN_PREFIXES = (
    'acs.webapp',
    'acs.ui_',
    'acs.stage1_',
    'webview',
    'pywebview',
    'sqlite3',
    'tkinter',
)


class ArchitectureBoundaryTests(unittest.TestCase):
    @staticmethod
    def imports_for(relative):
        path = Path(relative)
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=relative)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return imports

    def test_declared_core_module_set_is_complete_and_unique(self):
        self.assertEqual(len(CORE_MODULES), len(set(CORE_MODULES)))
        missing = [relative for relative in CORE_MODULES if not Path(relative).is_file()]
        self.assertEqual(missing, [], f'missing declared core modules: {missing}')
        required = {
            'acs/bookdocument.py',
            'acs/book_index.py',
            'acs/bookreader.py',
            'acs/training.py',
            'acs/game_lifecycle.py',
            'acs/game_identity.py',
            'acs/duplicate_detection.py',
            'acs/gametree.py',
            'acs/interaction_contracts.py',
            'acs/interaction_router.py',
        }
        self.assertEqual(required.difference(CORE_MODULES), set())

    def test_reusable_core_modules_do_not_depend_on_presentation_or_database_implementations(self):
        violations = []
        for relative in CORE_MODULES:
            for name in self.imports_for(relative):
                if name.startswith(FORBIDDEN_PREFIXES):
                    violations.append(f'{relative}: forbidden dependency {name}')
        self.assertEqual(violations, [], '\n'.join(violations))

    def test_engine_provider_port_does_not_import_concrete_engine_adapter(self):
        imports = self.imports_for('acs/engine_ports.py')
        self.assertNotIn('subprocess', imports)
        self.assertNotIn('acs.engine', imports)
        self.assertNotIn('engine', imports)

    def test_extension_registries_stay_presentation_and_infrastructure_neutral(self):
        for relative in ('acs/notation_registry.py', 'acs/sound_dispatch.py'):
            imports = self.imports_for(relative)
            self.assertNotIn('subprocess', imports)
            self.assertNotIn('pathlib', imports)
            self.assertNotIn('os', imports)

    def test_interaction_contracts_do_not_import_chess_state_or_platform_adapters(self):
        forbidden = {
            'acs.chesscore', 'acs.board_service', 'acs.position_editor', 'acs.webapp',
            'sqlite3', 'subprocess', 'pywebview', 'tkinter',
        }
        for relative in ('acs/interaction_contracts.py', 'acs/interaction_router.py'):
            imports = self.imports_for(relative)
            self.assertEqual(sorted(forbidden.intersection(imports)), [], relative)


if __name__ == '__main__':
    unittest.main()
