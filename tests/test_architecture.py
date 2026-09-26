import ast
from pathlib import Path
import unittest


CORE_MODULES = (
    'acs/chesscore.py',
    'acs/gametree.py',
    'acs/bookdocument.py',
    'acs/history.py',
    'acs/keybindings.py',
    'acs/notation.py',
    'acs/notation_registry.py',
    'acs/engine_ports.py',
    'acs/engine_play_service.py',
    'acs/analysis_service.py',
    'acs/sound_dispatch.py',
)

FORBIDDEN_PREFIXES = (
    'acs.webapp',
    'webview',
    'pywebview',
    'sqlite3',
    'tkinter',
)


class ArchitectureBoundaryTests(unittest.TestCase):
    @staticmethod
    def _imports_from_tree(relative, tree):
        package_parts = list(Path(relative).with_suffix('').parts[:-1])
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
                continue
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level == 0:
                if node.module:
                    imports.append(node.module)
                continue

            ascend = node.level - 1
            if ascend > len(package_parts):
                imports.append('<invalid-relative-import>')
                continue
            base = package_parts[:len(package_parts) - ascend]
            if node.module:
                imports.append('.'.join((*base, *node.module.split('.'))))
            else:
                imports.extend('.'.join((*base, alias.name)) for alias in node.names)
        return imports

    @classmethod
    def imports_for(cls, relative):
        path = Path(relative)
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=relative)
        return cls._imports_from_tree(relative, tree)

    @classmethod
    def imports_from_source(cls, relative, source):
        return cls._imports_from_tree(relative, ast.parse(source, filename=relative))

    def test_relative_imports_are_package_qualified_before_boundary_checks(self):
        imports = self.imports_from_source(
            'acs/example.py',
            'from .webapp import AccessibleChessAPI\n'
            'from . import webapp\n'
            'from .submodule import value\n',
        )
        self.assertEqual(
            imports,
            ['acs.webapp', 'acs.webapp', 'acs.submodule'],
        )
        self.assertTrue(
            any(name.startswith(FORBIDDEN_PREFIXES) for name in imports),
            'relative presentation imports must remain visible to architecture gates',
        )

    def test_parent_relative_imports_are_resolved_from_the_importing_package(self):
        imports = self.imports_from_source(
            'acs/contracts/example.py',
            'from ..webapp import AccessibleChessAPI\n'
            'from .. import webapp\n',
        )
        self.assertEqual(imports, ['acs.webapp', 'acs.webapp'])

    def test_engine_core_modules_do_not_depend_on_presentation_or_database_implementations(self):
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


if __name__ == '__main__':
    unittest.main()
