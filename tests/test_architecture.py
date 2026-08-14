import ast
from pathlib import Path
import unittest


CORE_MODULES = (
    'acs/history.py',
    'acs/keybindings.py',
    'acs/notation.py',
    'acs/engine_ports.py',
    'acs/engine_play_service.py',
    'acs/analysis_service.py',
)

FORBIDDEN_PREFIXES = (
    'acs.webapp',
    'webview',
    'pywebview',
    'sqlite3',
    'tkinter',
)


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_engine_core_modules_do_not_depend_on_presentation_or_database_implementations(self):
        violations = []
        for relative in CORE_MODULES:
            path = Path(relative)
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=relative)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for name in names:
                    if name.startswith(FORBIDDEN_PREFIXES):
                        violations.append(f'{relative}: forbidden dependency {name}')
        self.assertEqual(violations, [], '\n'.join(violations))

    def test_engine_provider_port_does_not_import_subprocess_adapter(self):
        text = Path('acs/engine_ports.py').read_text(encoding='utf-8')
        self.assertNotIn('subprocess', text)
        self.assertNotIn('UCIEngine', text)


if __name__ == '__main__':
    unittest.main()
