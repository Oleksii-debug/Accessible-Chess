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

ENTITLEMENT_POLICY_SOURCES = (
    'acs/entitlements.py',
    'acs/security_contracts.py',
)

ENTITLEMENT_FORBIDDEN_IMPORT_PREFIXES = (
    'stripe',
    'paddle',
    'requests',
    'httpx',
    'urllib',
    'webview',
    'pywebview',
    'tkinter',
    'sqlite3',
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

    def test_entitlement_policy_has_single_source_of_truth(self):
        """A merge must not leave parallel entitlement domain implementations.

        QA originally introduced security_contracts.py while Engine/Core later
        introduced entitlements.py. Both are valid branch-local experiments, but
        shipping both would create divergent state names, feature gates and policy
        semantics. Integration must choose one authoritative Core contract and
        adapt/delete the other rather than allowing both to coexist.
        """
        existing = [path for path in ENTITLEMENT_POLICY_SOURCES if Path(path).is_file()]
        self.assertLessEqual(
            len(existing),
            1,
            'duplicate entitlement policy sources: ' + ', '.join(existing),
        )

    def test_entitlement_policy_stays_provider_and_ui_neutral(self):
        """The authoritative policy module must remain pure and replaceable."""
        violations = []
        for relative in ENTITLEMENT_POLICY_SOURCES:
            if not Path(relative).is_file():
                continue
            for name in self.imports_for(relative):
                if name.startswith(ENTITLEMENT_FORBIDDEN_IMPORT_PREFIXES):
                    violations.append(f'{relative}: forbidden dependency {name}')
        self.assertEqual(violations, [], '\n'.join(violations))


if __name__ == '__main__':
    unittest.main()
