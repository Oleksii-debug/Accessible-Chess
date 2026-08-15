from __future__ import annotations

"""Static preflight checks for a release-candidate source tree.

This module is QA/release infrastructure. It does not implement licensing. It
looks for high-confidence release blockers before an expensive Windows build:
duplicate entitlement ownership, accidentally committed private credentials,
and missing release-version metadata.
"""

from dataclasses import dataclass
import ast
from pathlib import Path
import re
from typing import Iterable


_SECURITY_OWNER_NAMES = frozenset(
    {
        "EntitlementState",
        "EntitlementService",
        "FeatureGate",
        "LicensePolicy",
        "BillingProvider",
        "AccountSession",
    }
)
_SECRET_ASSIGNMENT_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "client_secret",
        "private_key",
        "license_private_key",
        "stripe_secret_key",
        "signing_key",
        "refresh_token",
        "access_token",
    }
)
_SECRET_FILE_SUFFIXES = frozenset({".p12", ".pfx", ".pem", ".key", ".jks"})
_PRIVATE_KEY_MARKER = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_EXCLUDED_SOURCE_PARTS = frozenset(
    {".git", ".venv", "venv", "build", "dist", "build-nuitka", "tests", "docs", "examples"}
)


@dataclass(frozen=True, slots=True)
class PreflightDefect:
    code: str
    path: str
    message: str

    def render(self) -> str:
        location = f" [{self.path}]" if self.path else ""
        return f"{self.code}{location}: {self.message}"


def _python_files(root: Path) -> Iterable[Path]:
    """Yield production Python sources, excluding test/docs/build fixtures."""

    for path in sorted(root.rglob("*.py"), key=lambda item: item.as_posix().casefold()):
        relative_parts = path.relative_to(root).parts
        if any(part in _EXCLUDED_SOURCE_PARTS for part in relative_parts):
            continue
        yield path


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> tuple[str, ...]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id.casefold())
    return tuple(names)


def scan_release_source_tree(root: str | Path) -> tuple[PreflightDefect, ...]:
    """Return high-confidence source-tree defects that should block packaging."""

    project_root = Path(root)
    if not project_root.is_dir():
        return (PreflightDefect("PREFLIGHT_ROOT", "", f"source root is not a directory: {project_root}"),)

    defects: list[PreflightDefect] = []
    version_file = project_root / "VERSION.txt"
    if not version_file.is_file() or not version_file.read_text(encoding="utf-8", errors="replace").strip():
        defects.append(PreflightDefect("VERSION_MISSING", "VERSION.txt", "release version source-of-truth is missing or empty"))

    owners: dict[str, list[str]] = {name: [] for name in _SECURITY_OWNER_NAMES}

    for path in _python_files(project_root):
        relative = path.relative_to(project_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            defects.append(PreflightDefect("PYTHON_PARSE", relative, f"cannot safely inspect source: {exc}"))
            continue

        if _PRIVATE_KEY_MARKER.search(text):
            defects.append(PreflightDefect("PRIVATE_KEY_LITERAL", relative, "private-key material is embedded in source"))

        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in owners:
                owners[node.name].append(relative)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = _literal_string(node.value)
                if not value:
                    continue
                for name in _assignment_names(node):
                    if name in _SECRET_ASSIGNMENT_NAMES and len(value.strip()) >= 12:
                        defects.append(
                            PreflightDefect(
                                "HARDCODED_SECRET",
                                relative,
                                f"high-risk credential variable {name!r} contains a literal value",
                            )
                        )

    for name, paths in owners.items():
        unique_paths = sorted(set(paths))
        if len(unique_paths) > 1:
            defects.append(
                PreflightDefect(
                    "DUPLICATE_SECURITY_OWNER",
                    ", ".join(unique_paths),
                    f"{name} has multiple source-of-truth definitions; keep one neutral contract owner",
                )
            )

    for path in sorted(project_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(project_root).as_posix()
        if path.suffix.casefold() in _SECRET_FILE_SUFFIXES:
            defects.append(
                PreflightDefect(
                    "SECRET_FILE",
                    relative,
                    "private credential/signing-key container must not be committed or packaged",
                )
            )

    return tuple(defects)


def assert_release_source_tree(root: str | Path) -> None:
    defects = scan_release_source_tree(root)
    if defects:
        raise RuntimeError("RELEASE SOURCE PREFLIGHT FAILED:\n" + "\n".join(item.render() for item in defects))
