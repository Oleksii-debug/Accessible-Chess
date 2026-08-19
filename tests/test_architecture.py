import ast
from pathlib import Path
import unittest


CORE_MODULES = (
    'acs/squares.py',
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
