import ast
from pathlib import Path
import unittest


# Presentation-neutral reusable modules. Keep this list explicit so adding a
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
)

# Application/storage orchestration can consume concrete persistence. It is
# intentionally classified outside CORE_MODULES rather than being falsely
# certified as database-neutral reusable core.
STORAGE_ORCHESTRATION_MODULES = (
    'acs/duplicate_detection.py',
)

CHESSBASE_READ_ONLY_MODULES = (
    'acs/chessbase_capabilities.py',
    'acs/chessbase_cbh.py',
    'acs/chessbase_cbg.py',
    'acs/chessbase_cbg_payload.py',
    'acs/chessbase_cbg_payload_evidence.py',
    'acs/chessbase_cbp.py',
    'acs/chessbase_cbt.py',
    'acs/chessbase_cbh_cbg_link.py',
    'acs/chessbase_cbh_cbg_batch.py',
    'acs/chessbase_cbh_metadata.py',
    'acs/chessbase_cbh_evidence.py',
)

FORBIDDEN_PREFIXES = (
    'acs.webapp',
    'acs.ui_',
    'acs.stage1_',
    'acs.acsdb',
    'webview',
    'pywebview',
    'sqlite3',
    'tkinter',
)


def _module_name_for_path(relative: str) -> str:
    return '.'.join(Path(relative).with_suffix('').parts)


def _resolve_import_from(relative: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ''

    package_parts = _module_name_for_path(relative).split('.')[:-1]
    ascend = node.level - 1
    if ascend > len(package_parts):
        return node.module or ''
    if ascend:
        package_parts = package_parts[:-ascend]
    if node.module:
        package_parts.extend(node.module.split('.'))
    return '.'.join(package_parts)


def imports_from_source(relative: str, source: str) -> list[str]:
    tree = ast.parse(source, filename=relative)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(relative, node)
            if node.module:
                if base:
                    imports.append(base)
            else:
                imports.extend(
                    f'{base}.{alias.name}' if base else alias.name
                    for alias in node.names
                )
    return imports


def imports_for(relative: str) -> list[str]:
    path = Path(relative)
    return imports_from_source(relative, path.read_text(encoding='utf-8'))


def forbidden_imports(imports: list[str]) -> list[str]:
    return [name for name in imports if name.startswith(FORBIDDEN_PREFIXES)]


class ArchitectureBoundaryTests(unittest.TestCase):
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
            'acs/gametree.py',
            'acs/interaction_contracts.py',
            'acs/interaction_router.py',
        }
        self.assertEqual(required.difference(CORE_MODULES), set())

    def test_storage_orchestration_is_not_misclassified_as_reusable_core(self):
        self.assertIn('acs/duplicate_detection.py', STORAGE_ORCHESTRATION_MODULES)
        self.assertNotIn('acs/duplicate_detection.py', CORE_MODULES)
        imports = imports_for('acs/duplicate_detection.py')
        self.assertIn('acs.acsdb', imports)
        self.assertIn('acs.acsdb', forbidden_imports(imports))

    def test_reusable_core_modules_do_not_depend_on_presentation_or_database_implementations(self):
        violations = []
        for relative in CORE_MODULES:
            for name in forbidden_imports(imports_for(relative)):
                violations.append(f'{relative}: forbidden dependency {name}')
        self.assertEqual(violations, [], '\n'.join(violations))

    def test_relative_imports_are_resolved_before_forbidden_prefix_checks(self):
        samples = (
            ('from .acsdb import AcsDatabase', 'acs.acsdb'),
            ('from . import webapp', 'acs.webapp'),
            ('from .ui_board import Board', 'acs.ui_board'),
            ('from .stage1_windows import Runner', 'acs.stage1_windows'),
        )
        for source, expected in samples:
            with self.subTest(source=source):
                imports = imports_from_source('acs/example.py', source)
                self.assertIn(expected, imports)
                self.assertIn(expected, forbidden_imports(imports))

    def test_engine_provider_port_does_not_import_concrete_engine_adapter(self):
        imports = imports_for('acs/engine_ports.py')
        self.assertNotIn('subprocess', imports)
        self.assertNotIn('acs.engine', imports)
        self.assertNotIn('engine', imports)

    def test_extension_registries_stay_presentation_and_infrastructure_neutral(self):
        for relative in ('acs/notation_registry.py', 'acs/sound_dispatch.py'):
            imports = imports_for(relative)
            self.assertNotIn('subprocess', imports)
            self.assertNotIn('pathlib', imports)
            self.assertNotIn('os', imports)

    def test_interaction_contracts_do_not_import_chess_state_or_platform_adapters(self):
        forbidden = {
            'acs.chesscore', 'acs.board_service', 'acs.position_editor', 'acs.webapp',
            'sqlite3', 'subprocess', 'pywebview', 'tkinter',
        }
        for relative in ('acs/interaction_contracts.py', 'acs/interaction_router.py'):
            imports = imports_for(relative)
            self.assertEqual(sorted(forbidden.intersection(imports)), [], relative)

    def test_chessbase_layout_adapters_remain_neutral_and_gpl_dependency_free(self):
        violations = []
        for relative in CHESSBASE_READ_ONLY_MODULES:
            self.assertTrue(Path(relative).is_file(), relative)
            for name in imports_for(relative):
                if name == 'chess' or name.startswith('chess.'):
                    violations.append(f'{relative}: GPL python-chess dependency {name}')
                if name in {'sqlite3', 'subprocess'} or name.startswith('acs.webapp'):
                    violations.append(f'{relative}: non-neutral dependency {name}')
        self.assertEqual(violations, [], '\n'.join(violations))

    def test_chessbase_adaptation_has_pinned_mit_notice(self):
        notice = Path('THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
        self.assertIn('42b3592738062db1f768239e85df1b98cb1cead9', notice)
        self.assertIn('Copyright (c) 2022 Dominik Klein', notice)
        self.assertIn('MIT License', notice)


if __name__ == '__main__':
    unittest.main()
