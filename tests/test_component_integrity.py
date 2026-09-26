from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from acs.component_integrity import (
    ComponentIntegrityError,
    INTEGRITY_MANIFEST_SCHEMA,
    verify_protected_components,
)


def manifest_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    document = {
        "schema": INTEGRITY_MANIFEST_SCHEMA,
        "components": [
            {"path": path, "sha256": sha256(content).hexdigest()}
            for path, content in entries
        ],
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def trusted_digest(manifest: bytes) -> str:
    return sha256(manifest).hexdigest()


class ComponentIntegrityTests(unittest.TestCase):
    def test_valid_exact_component_set_is_verified_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "acs").mkdir()
            first = b"runtime-core\n"
            second = b"provider-config\n"
            (root / "acs" / "online.py").write_bytes(first)
            (root / "acs" / "provider.json").write_bytes(second)
            user_document = root / "user-game.pgn"
            user_document.write_text("1. e4 e5 *\n", encoding="utf-8")
            before = user_document.read_bytes()

            manifest = manifest_bytes([
                ("acs/online.py", first),
                ("acs/provider.json", second),
            ])
            report = verify_protected_components(
                manifest,
                trusted_manifest_sha256=trusted_digest(manifest),
                installation_root=root,
                required_paths=("acs/provider.json", "acs/online.py"),
            )

            self.assertEqual(report.verified_paths, ("acs/online.py", "acs/provider.json"))
            self.assertEqual(report.manifest_sha256, trusted_digest(manifest))
            self.assertEqual(user_document.read_bytes(), before)

    def test_untrusted_manifest_fails_before_filesystem_dependency(self) -> None:
        manifest = manifest_bytes([("acs/online.py", b"expected")])
        with self.assertRaisesRegex(ComponentIntegrityError, "manifest is not trusted"):
            verify_protected_components(
                manifest,
                trusted_manifest_sha256="0" * 64,
                installation_root="definitely-does-not-exist",
                required_paths=("acs/online.py",),
            )

    def test_tampered_component_fails_and_is_not_deleted_or_modified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "acs").mkdir()
            component = root / "acs" / "online.py"
            component.write_bytes(b"tampered")
            manifest = manifest_bytes([("acs/online.py", b"expected")])

            with self.assertRaisesRegex(ComponentIntegrityError, "integrity check failed"):
                verify_protected_components(
                    manifest,
                    trusted_manifest_sha256=trusted_digest(manifest),
                    installation_root=root,
                    required_paths=("acs/online.py",),
                )
            self.assertEqual(component.read_bytes(), b"tampered")
            self.assertTrue(component.exists())

    def test_missing_component_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = manifest_bytes([("acs/missing.py", b"expected")])
            with self.assertRaisesRegex(ComponentIntegrityError, "unavailable"):
                verify_protected_components(
                    manifest,
                    trusted_manifest_sha256=trusted_digest(manifest),
                    installation_root=directory,
                    required_paths=("acs/missing.py",),
                )

    def test_manifest_must_exactly_cover_callers_protected_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "acs").mkdir()
            (root / "acs" / "online.py").write_bytes(b"online")
            manifest = manifest_bytes([("acs/online.py", b"online")])
            with self.assertRaisesRegex(ComponentIntegrityError, "exactly cover"):
                verify_protected_components(
                    manifest,
                    trusted_manifest_sha256=trusted_digest(manifest),
                    installation_root=root,
                    required_paths=("acs/online.py", "acs/provider.json"),
                )

    def test_required_paths_iteration_is_bounded_before_materialization(self) -> None:
        manifest = manifest_bytes([("acs/online.py", b"online")])
        yielded = 0

        def unbounded_paths():
            nonlocal yielded
            while True:
                yielded += 1
                yield f"acs/component-{yielded:04d}.py"

        with self.assertRaisesRegex(ComponentIntegrityError, "bounded and non-empty"):
            verify_protected_components(
                manifest,
                trusted_manifest_sha256=trusted_digest(manifest),
                installation_root=".",
                required_paths=unbounded_paths(),
            )
        self.assertEqual(yielded, 513)

    def test_traversal_absolute_drive_and_backslash_paths_fail_closed(self) -> None:
        bad_paths = [
            "../secret.txt",
            "/absolute.txt",
            "C:/Windows/System32/kernel32.dll",
            "acs\\online.py",
            "acs/../secret.txt",
            "acs//online.py",
        ]
        for bad_path in bad_paths:
            with self.subTest(path=bad_path):
                manifest = manifest_bytes([(bad_path, b"x")])
                with self.assertRaises(ComponentIntegrityError):
                    verify_protected_components(
                        manifest,
                        trusted_manifest_sha256=trusted_digest(manifest),
                        installation_root=".",
                        required_paths=(bad_path,),
                    )

    def test_windows_reserved_and_trailing_dot_paths_fail_closed(self) -> None:
        for bad_path in ("acs/CON.txt", "acs/provider.json.", "NUL", "acs/LPT1.cfg"):
            with self.subTest(path=bad_path):
                manifest = manifest_bytes([(bad_path, b"x")])
                with self.assertRaises(ComponentIntegrityError):
                    verify_protected_components(
                        manifest,
                        trusted_manifest_sha256=trusted_digest(manifest),
                        installation_root=".",
                        required_paths=(bad_path,),
                    )

    def test_case_insensitive_component_collision_fails_on_all_platforms(self) -> None:
        manifest = manifest_bytes([
            ("acs/Online.py", b"A"),
            ("acs/online.py", b"B"),
        ])
        with self.assertRaisesRegex(ComponentIntegrityError, "case folding"):
            verify_protected_components(
                manifest,
                trusted_manifest_sha256=trusted_digest(manifest),
                installation_root=".",
                required_paths=("acs/Online.py", "acs/online.py"),
            )

    def test_component_entries_must_be_deterministically_sorted(self) -> None:
        manifest = manifest_bytes([
            ("acs/z.py", b"z"),
            ("acs/a.py", b"a"),
        ])
        with self.assertRaisesRegex(ComponentIntegrityError, "sorted"):
            verify_protected_components(
                manifest,
                trusted_manifest_sha256=trusted_digest(manifest),
                installation_root=".",
                required_paths=("acs/a.py", "acs/z.py"),
            )

    def test_duplicate_and_unknown_json_fields_fail_closed(self) -> None:
        duplicate = (
            b'{"schema":"accessible-chess-component-integrity-v1",'
            b'"schema":"accessible-chess-component-integrity-v1",'
            b'"components":[]}'
        )
        with self.assertRaisesRegex(ComponentIntegrityError, "duplicate"):
            verify_protected_components(
                duplicate,
                trusted_manifest_sha256=trusted_digest(duplicate),
                installation_root=".",
                required_paths=("acs/x.py",),
            )

        document = {
            "schema": INTEGRITY_MANIFEST_SCHEMA,
            "components": [{"path": "acs/x.py", "sha256": "0" * 64, "size": 1}],
        }
        unknown = json.dumps(document).encode("utf-8")
        with self.assertRaisesRegex(ComponentIntegrityError, "fields are invalid"):
            verify_protected_components(
                unknown,
                trusted_manifest_sha256=trusted_digest(unknown),
                installation_root=".",
                required_paths=("acs/x.py",),
            )

    def test_hash_and_manifest_digest_must_be_canonical_lowercase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = json.dumps({
                "schema": INTEGRITY_MANIFEST_SCHEMA,
                "components": [{"path": "acs/x.py", "sha256": "A" * 64}],
            }).encode("utf-8")
            with self.assertRaisesRegex(ComponentIntegrityError, "lowercase SHA-256"):
                verify_protected_components(
                    manifest,
                    trusted_manifest_sha256=trusted_digest(manifest),
                    installation_root=directory,
                    required_paths=("acs/x.py",),
                )
            valid_manifest = manifest_bytes([("acs/x.py", b"x")])
            with self.assertRaisesRegex(ComponentIntegrityError, "lowercase SHA-256"):
                verify_protected_components(
                    valid_manifest,
                    trusted_manifest_sha256=trusted_digest(valid_manifest).upper(),
                    installation_root=directory,
                    required_paths=("acs/x.py",),
                )

    def test_component_size_bound_prevents_unbounded_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "acs").mkdir()
            content = b"12345"
            (root / "acs" / "online.py").write_bytes(content)
            manifest = manifest_bytes([("acs/online.py", content)])
            with self.assertRaisesRegex(ComponentIntegrityError, "size bound"):
                verify_protected_components(
                    manifest,
                    trusted_manifest_sha256=trusted_digest(manifest),
                    installation_root=root,
                    required_paths=("acs/online.py",),
                    max_component_bytes=4,
                )

    def test_symbolic_link_component_fails_closed_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "acs").mkdir()
            target = root / "real.py"
            target.write_bytes(b"real")
            link = root / "acs" / "online.py"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are unavailable in this environment")
            manifest = manifest_bytes([("acs/online.py", b"real")])
            with self.assertRaisesRegex(ComponentIntegrityError, "symbolic link"):
                verify_protected_components(
                    manifest,
                    trusted_manifest_sha256=trusted_digest(manifest),
                    installation_root=root,
                    required_paths=("acs/online.py",),
                )


if __name__ == "__main__":
    unittest.main()