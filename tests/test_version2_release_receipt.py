from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from acs.version2_package_preflight import Version2PackagePreflightError
from acs import version2_release_receipt as release_receipt_module
from acs.version2_release_receipt import (
    CANONICAL_W5_WORKFLOW,
    RELEASE_RECEIPT_SCHEMA_VERSION,
    REPOSITORY_FULL_NAME,
    Version2ReleaseReceiptError,
    build_version2_release_receipt,
    main,
    read_version2_release_receipt,
    verify_version2_release_receipt,
    write_version2_release_receipt,
)
from tests.test_version2_package_preflight import _SHA, _make_tree


_HEAD_SHA = "b" * 40


def _zip_tree(
    root: Path,
    archive_path: Path,
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=compression) as archive:
        for path in sorted(
            (item for item in root.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(root).as_posix().casefold(),
        ):
            archive.write(path, path.relative_to(root).as_posix())


def _fixture(td: str) -> tuple[Path, Path]:
    base = Path(td)
    root = base / "package"
    root.mkdir()
    _make_tree(root)
    archive = base / "accessible-chess.zip"
    _zip_tree(root, archive)
    return root, archive


def _build(archive: Path, **kwargs):
    arguments = {
        "expected_integration_sha": _SHA,
        "workflow_run_id": 37139145605,
        "workflow_run_attempt": 1,
        "qualification_head_sha": _HEAD_SHA,
        "artifact_id": 11282014673,
        "artifact_name": "dostupni-shakhy-w5exact-win-x64-standalone",
    }
    arguments.update(kwargs)
    return build_version2_release_receipt(archive, **arguments)


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


class Version2ReleaseReceiptTests(unittest.TestCase):
    def test_receipt_binds_validated_zip_and_attributable_action_identity(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)

            self.assertEqual(receipt.schema_version, RELEASE_RECEIPT_SCHEMA_VERSION)
            self.assertEqual(receipt.product, "Accessible Chess")
            self.assertEqual(receipt.repository, REPOSITORY_FULL_NAME)
            self.assertEqual(receipt.workflow_path, CANONICAL_W5_WORKFLOW)
            self.assertEqual(receipt.workflow_run_id, 37139145605)
            self.assertEqual(receipt.workflow_run_attempt, 1)
            self.assertEqual(receipt.qualification_head_sha, _HEAD_SHA)
            self.assertEqual(receipt.artifact_id, 11282014673)
            self.assertEqual(
                receipt.package_sha256,
                hashlib.sha256(archive.read_bytes()).hexdigest(),
            )
            self.assertEqual(receipt.integration_sha, _SHA)
            self.assertGreater(receipt.inventory_files, 0)
            self.assertGreater(receipt.total_bytes, 0)
            self.assertGreater(receipt.checksums_verified, 0)
            self.assertRegex(receipt.inventory_sha256, r"^[0-9a-f]{64}$")

            payload = json.loads(receipt.to_json())
            self.assertEqual(payload["package_sha256"], receipt.package_sha256)
            self.assertNotIn(str(archive), receipt.to_json())

    def test_receipt_reuses_canonical_zip_preflight_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            archive.write_bytes(b"not-a-zip")
            with self.assertRaises(Version2PackagePreflightError):
                _build(archive)

    def test_receipt_rejects_wrong_integration_authority(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "integration_sha does not match",
            ):
                _build(archive, expected_integration_sha="c" * 40)

    def test_metadata_is_strict_and_bools_are_not_ids(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            invalid = (
                {"workflow_run_id": True},
                {"workflow_run_id": 0},
                {"workflow_run_attempt": False},
                {"workflow_run_attempt": 0},
                {"artifact_id": False},
                {"artifact_id": -1},
                {"qualification_head_sha": "B" * 40},
                {"qualification_head_sha": "b" * 39},
                {"artifact_name": "../artifact"},
                {"artifact_name": "artifact\nspoof"},
                {"artifact_name": " artifact"},
            )
            for override in invalid:
                with self.subTest(override=override), self.assertRaises(
                    Version2ReleaseReceiptError
                ):
                    _build(archive, **override)

    def test_receipt_json_is_canonical_and_output_is_no_replace(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "release-receipt.json"

            write_version2_release_receipt(output, receipt)
            raw = output.read_text(encoding="utf-8")
            self.assertEqual(raw, receipt.to_json())
            self.assertTrue(raw.endswith("\n"))
            self.assertEqual(len(raw.splitlines()), 1)
            self.assertEqual(read_version2_release_receipt(output), receipt)
            self.assertEqual(verify_version2_release_receipt(output, archive), receipt)

            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "overwrite is forbidden",
            ):
                write_version2_release_receipt(output, receipt)
            self.assertEqual(output.read_text(encoding="utf-8"), raw)

    def test_receipt_readback_rejects_symlink_and_path_identity_change(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            write_version2_release_receipt(output, receipt)

            link = Path(td) / "receipt-link.json"
            try:
                link.symlink_to(output)
            except (OSError, NotImplementedError):
                pass
            else:
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "must not be a symlink or reparse point",
                ):
                    read_version2_release_receipt(link)

            with patch(
                "acs.version2_release_receipt._same_file_snapshot",
                side_effect=(True, True, False),
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "changed while being read",
                ):
                    read_version2_release_receipt(output)

    def test_receipt_identity_fallback_rejects_unknown_and_boolean_ids(self):
        valid = SimpleNamespace(st_dev=11, st_ino=22)
        same = SimpleNamespace(st_dev=11, st_ino=22)
        invalid_pairs = (
            (
                SimpleNamespace(st_dev=0, st_ino=0),
                SimpleNamespace(st_dev=0, st_ino=0),
            ),
            (
                SimpleNamespace(st_dev=None, st_ino=None),
                SimpleNamespace(st_dev=None, st_ino=None),
            ),
            (
                SimpleNamespace(st_dev=True, st_ino=22),
                SimpleNamespace(st_dev=True, st_ino=22),
            ),
            (
                SimpleNamespace(st_dev=11, st_ino=False),
                SimpleNamespace(st_dev=11, st_ino=False),
            ),
        )
        with patch.object(
            release_receipt_module.os.path,
            "samestat",
            side_effect=OSError("identity unavailable"),
        ):
            self.assertTrue(
                release_receipt_module._same_file_identity(valid, same)
            )
            for left, right in invalid_pairs:
                with self.subTest(left=left, right=right):
                    self.assertFalse(
                        release_receipt_module._same_file_identity(left, right)
                    )

    def test_receipt_snapshot_metadata_is_platform_fail_closed(self):
        base = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )
        ctime_drift = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=999,
        )
        missing_mtime = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_ctime_ns=456,
        )
        missing_ctime = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
        )
        bool_size = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=True,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )

        with patch.object(
            release_receipt_module,
            "_same_file_identity",
            return_value=True,
        ):
            with patch.object(release_receipt_module.os, "name", "nt"):
                self.assertTrue(
                    release_receipt_module._same_file_snapshot(
                        base,
                        ctime_drift,
                    )
                )
                self.assertFalse(
                    release_receipt_module._same_file_snapshot(
                        base,
                        missing_mtime,
                    )
                )

            with patch.object(release_receipt_module.os, "name", "posix"):
                self.assertTrue(
                    release_receipt_module._same_file_snapshot(base, base)
                )
                self.assertFalse(
                    release_receipt_module._same_file_snapshot(
                        base,
                        ctime_drift,
                    )
                )
                self.assertFalse(
                    release_receipt_module._same_file_snapshot(
                        base,
                        missing_ctime,
                    )
                )
                self.assertFalse(
                    release_receipt_module._same_file_snapshot(
                        base,
                        bool_size,
                    )
                )

    def test_receipt_publication_snapshot_ignores_ctime_but_requires_mtime(self):
        base = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )
        ctime_drift = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=999,
        )
        mtime_drift = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=124,
            st_ctime_ns=456,
        )
        missing_mtime = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_ctime_ns=456,
        )

        with patch.object(
            release_receipt_module,
            "_same_file_identity",
            return_value=True,
        ):
            self.assertTrue(
                release_receipt_module._same_publication_snapshot(
                    base,
                    ctime_drift,
                )
            )
            self.assertFalse(
                release_receipt_module._same_publication_snapshot(
                    base,
                    mtime_drift,
                )
            )
            self.assertFalse(
                release_receipt_module._same_publication_snapshot(
                    base,
                    missing_mtime,
                )
            )

    def test_receipt_write_fsyncs_and_rechecks_staging_identity(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"

            with patch(
                "acs.version2_release_receipt._sync_published_zip_namespace",
                side_effect=lambda _path, *, expected: expected,
            ) as namespace_sync, patch(
                "acs.version2_release_receipt.os.fsync"
            ) as fsync:
                write_version2_release_receipt(output, receipt)
            fsync.assert_called_once()
            namespace_sync.assert_called_once()
            self.assertEqual(read_version2_release_receipt(output), receipt)

            swapped = Path(td) / "swapped.json"
            with patch(
                "acs.version2_release_receipt._same_file_identity",
                return_value=False,
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "staging file changed while being written",
                ):
                    write_version2_release_receipt(swapped, receipt)
            self.assertFalse(swapped.exists())
            self.assertEqual(
                list(Path(td).glob(".swapped.json.receipt-*.tmp")),
                [],
            )

    def test_receipt_publication_crosses_namespace_durability_barrier(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"

            original = release_receipt_module._sync_published_zip_namespace
            with patch(
                "acs.version2_release_receipt._sync_published_zip_namespace",
                wraps=original,
            ) as namespace_sync:
                write_version2_release_receipt(output, receipt)

            self.assertEqual(namespace_sync.call_count, 1)
            args, kwargs = namespace_sync.call_args
            self.assertEqual(Path(args[0]), output)
            self.assertIn("expected", kwargs)
            self.assertEqual(read_version2_release_receipt(output), receipt)

    def test_post_staging_cleanup_mutation_rejects_owned_receipt_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            real_remove = release_receipt_module._remove_private_staging_file
            injected = False

            def remove_then_mutate(path, expected_identity):
                nonlocal injected
                candidate = Path(path)
                real_remove(candidate, expected_identity)
                if candidate != output and not injected:
                    payload = json.loads(receipt.to_json())
                    payload["artifact_id"] = int(payload["artifact_id"]) + 1
                    output.write_text(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    injected = True

            with patch(
                "acs.version2_release_receipt._remove_private_staging_file",
                side_effect=remove_then_mutate,
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "bytes changed after staging cleanup",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertTrue(injected)
            self.assertFalse(output.exists())

            write_version2_release_receipt(output, receipt)
            self.assertEqual(read_version2_release_receipt(output), receipt)

    def test_final_readback_in_place_mutation_is_rejected_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            real_read = release_receipt_module.read_version2_release_receipt
            injected = False

            def read_then_mutate(path):
                nonlocal injected
                value = real_read(path)
                candidate = Path(path)
                if candidate == output and not injected:
                    with candidate.open("ab") as handle:
                        handle.write(b" ")
                        handle.flush()
                    injected = True
                return value

            with patch(
                "acs.version2_release_receipt.read_version2_release_receipt",
                side_effect=read_then_mutate,
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "changed after final readback",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertTrue(injected)
            self.assertFalse(output.exists())

            write_version2_release_receipt(output, receipt)
            self.assertEqual(read_version2_release_receipt(output), receipt)

    def test_post_link_durability_failure_cleans_owned_receipt_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"

            with patch(
                "acs.version2_release_receipt._sync_published_zip_namespace",
                side_effect=release_receipt_module.Version2PortablePackageError(
                    "simulated namespace durability failure"
                ),
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "publication durability could not be confirmed",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertFalse(output.exists())
            write_version2_release_receipt(output, receipt)
            self.assertEqual(read_version2_release_receipt(output), receipt)

    def test_failed_receipt_write_discards_own_partial_file_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"

            with patch(
                "acs.version2_release_receipt.os.fsync",
                side_effect=OSError("simulated durability failure"),
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "could not be written: OSError",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertFalse(output.exists())
            write_version2_release_receipt(output, receipt)
            self.assertEqual(read_version2_release_receipt(output), receipt)

    def test_fsync_failure_never_creates_canonical_path_even_when_identity_is_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"

            with patch(
                "acs.version2_release_receipt.os.fsync",
                side_effect=OSError("simulated durability failure"),
            ), patch(
                "acs.version2_release_receipt._same_file_identity",
                return_value=False,
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "could not be written: OSError",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertFalse(output.exists())
            self.assertEqual(
                list(Path(td).glob(".receipt.json.receipt-*.tmp")),
                [],
            )

    def test_failed_staging_identity_read_never_creates_canonical_path(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"

            with patch(
                "acs.version2_release_receipt.os.fstat",
                side_effect=OSError("simulated identity failure"),
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "could not be written: OSError",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertFalse(output.exists())
            leftovers = list(Path(td).glob(".receipt.json.receipt-*.tmp"))
            self.assertEqual(len(leftovers), 1)
            self.assertEqual(leftovers[0].read_bytes(), b"")

    def test_rejected_own_canonical_link_is_removed_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"

            # The hard link is already created when the last publication
            # snapshot comparison rejects the candidate.  That failed call must
            # remove only its own canonical link so an exact retry is possible.
            with patch(
                "acs.version2_release_receipt._same_file_snapshot",
                side_effect=(True, True, True, False),
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "changed during atomic publication",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertFalse(output.exists())
            self.assertEqual(
                list(Path(td).glob(".receipt.json.receipt-*.tmp")),
                [],
            )

            write_version2_release_receipt(output, receipt)
            self.assertEqual(read_version2_release_receipt(output), receipt)

    def test_publication_identity_failure_never_unlinks_replacement_path(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            real_link = __import__("os").link

            def link_then_replace(source, destination, **kwargs):
                real_link(source, destination, **kwargs)
                target = Path(destination)
                target.unlink()
                target.write_bytes(b"replacement-owned-by-another-writer")

            with patch(
                "acs.version2_release_receipt.os.link",
                side_effect=link_then_replace,
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "changed during atomic publication",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertEqual(
                output.read_bytes(),
                b"replacement-owned-by-another-writer",
            )
            self.assertEqual(
                list(Path(td).glob(".receipt.json.receipt-*.tmp")),
                [],
            )

    def test_staging_path_replacement_during_link_is_not_accepted_or_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            real_link = __import__("os").link

            def replace_staging_then_link(source, destination, **kwargs):
                staged = Path(source)
                staged.unlink()
                staged.write_bytes(b"replacement-staging-owned-by-another-writer")
                real_link(source, destination, **kwargs)

            with patch(
                "acs.version2_release_receipt.os.link",
                side_effect=replace_staging_then_link,
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "changed during atomic publication",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertEqual(
                output.read_bytes(),
                b"replacement-staging-owned-by-another-writer",
            )
            leftovers = list(Path(td).glob(".receipt.json.receipt-*.tmp"))
            self.assertEqual(len(leftovers), 1)
            self.assertEqual(
                leftovers[0].read_bytes(),
                b"replacement-staging-owned-by-another-writer",
            )

    def test_cleanup_refuses_replaced_staging_after_post_link_error(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            real_link = __import__("os").link

            def link_then_replace_and_fail(source, destination, **kwargs):
                real_link(source, destination, **kwargs)
                staged = Path(source)
                staged.unlink()
                staged.write_bytes(b"replacement-staging-owned-by-another-writer")
                raise OSError("simulated post-link failure")

            with patch(
                "acs.version2_release_receipt.os.link",
                side_effect=link_then_replace_and_fail,
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "does not support safe atomic no-replace publication: OSError",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertEqual(output.read_text(encoding="utf-8"), receipt.to_json())
            leftovers = list(Path(td).glob(".receipt.json.receipt-*.tmp"))
            self.assertEqual(len(leftovers), 1)
            self.assertEqual(
                leftovers[0].read_bytes(),
                b"replacement-staging-owned-by-another-writer",
            )

    def test_hardlink_publication_failure_leaves_no_canonical_or_staging_file(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"

            with patch(
                "acs.version2_release_receipt.os.link",
                side_effect=OSError("hardlink unavailable"),
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "does not support safe atomic no-replace publication",
                ):
                    write_version2_release_receipt(output, receipt)

            self.assertFalse(output.exists())
            self.assertEqual(
                list(Path(td).glob(".receipt.json.receipt-*.tmp")),
                [],
            )

    def test_readback_rejects_duplicate_unknown_wrong_authority_and_reformatting(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            payload = json.loads(receipt.to_json())

            payload["repository"] = "somewhere/else"
            output.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "repository identity mismatch",
            ):
                read_version2_release_receipt(output)

            payload["repository"] = REPOSITORY_FULL_NAME
            payload["unexpected"] = True
            output.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "schema mismatch",
            ):
                read_version2_release_receipt(output)

            duplicate = receipt.to_json().rstrip("\n")
            duplicate = duplicate[:-1] + ',"artifact_id":1}'
            output.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "duplicate JSON key 'artifact_id'",
            ):
                read_version2_release_receipt(output)

            pretty = json.dumps(json.loads(receipt.to_json()), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            output.write_text(pretty, encoding="utf-8")
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "not in canonical serialization",
            ):
                read_version2_release_receipt(output)

            output.write_text(receipt.to_json().rstrip("\n"), encoding="utf-8")
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "not in canonical serialization",
            ):
                read_version2_release_receipt(output)

    def test_readback_rejects_semantically_valid_but_different_zip_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root, archive = _fixture(td)
            receipt_path = Path(td) / "receipt.json"
            write_version2_release_receipt(receipt_path, _build(archive))

            alternate = Path(td) / "alternate.zip"
            _zip_tree(root, alternate, compression=zipfile.ZIP_STORED)
            self.assertNotEqual(
                hashlib.sha256(archive.read_bytes()).hexdigest(),
                hashlib.sha256(alternate.read_bytes()).hexdigest(),
            )
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "does not match the revalidated package bytes",
            ):
                verify_version2_release_receipt(receipt_path, alternate)

    def test_readback_rejects_tampered_digest_even_when_package_is_valid(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            payload = json.loads(receipt.to_json())
            payload["package_sha256"] = "0" * 64
            output.write_text(_canonical_json(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "does not match the revalidated package bytes",
            ):
                verify_version2_release_receipt(output, archive)

    def test_cli_create_and_verify_same_qualified_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            output = Path(td) / "receipt.json"
            create_result = main(
                [
                    "create",
                    "--package",
                    str(archive),
                    "--expected-integration-sha",
                    _SHA,
                    "--workflow-run-id",
                    "37139145605",
                    "--workflow-run-attempt",
                    "1",
                    "--qualification-head-sha",
                    _HEAD_SHA,
                    "--artifact-id",
                    "11282014673",
                    "--artifact-name",
                    "dostupni-shakhy-w5exact-win-x64-standalone",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(create_result, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["repository"], REPOSITORY_FULL_NAME)
            self.assertEqual(payload["workflow_run_id"], 37139145605)
            self.assertEqual(payload["workflow_run_attempt"], 1)
            self.assertEqual(payload["artifact_id"], 11282014673)
            self.assertEqual(payload["qualification_head_sha"], _HEAD_SHA)

            verify_result = main(
                [
                    "verify",
                    "--package",
                    str(archive),
                    "--receipt",
                    str(output),
                ]
            )
            self.assertEqual(verify_result, 0)
            self.assertEqual(
                verify_version2_release_receipt(output, archive),
                read_version2_release_receipt(output),
            )



    def test_writer_revalidates_direct_receipt_instances_before_io(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            payload = json.loads(receipt.to_json())
            output = Path(td) / "receipt.json"

            payload["workflow_run_id"] = True
            malformed = Version2ReleaseReceipt(**payload)
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "workflow_run_id must be a positive signed 64-bit integer",
            ):
                write_version2_release_receipt(output, malformed)
            self.assertFalse(output.exists())
            self.assertEqual(
                list(Path(td).glob(".receipt.json.receipt-*.tmp")),
                [],
            )

            class ActiveReceipt(Version2ReleaseReceipt):
                def to_json(self):
                    raise AssertionError("subclass method must not execute")

            active = ActiveReceipt(**json.loads(receipt.to_json()))
            with self.assertRaisesRegex(
                TypeError,
                "exact Version2ReleaseReceipt",
            ):
                write_version2_release_receipt(output, active)
            self.assertFalse(output.exists())

    def test_readback_rejects_nonfinite_json_and_contains_parser_recursion(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            canonical = receipt.to_json()
            needle = '"workflow_run_id":37139145605'
            self.assertIn(needle, canonical)

            for constant in ("NaN", "Infinity", "-Infinity"):
                with self.subTest(constant=constant):
                    raw = canonical.replace(
                        needle,
                        f'"workflow_run_id":{constant}',
                        1,
                    )
                    output.write_text(raw, encoding="utf-8")
                    with self.assertRaisesRegex(
                        Version2ReleaseReceiptError,
                        "non-finite JSON number",
                    ):
                        read_version2_release_receipt(output)

            output.write_text(canonical, encoding="utf-8")
            with patch(
                "acs.version2_release_receipt.json.loads",
                side_effect=RecursionError("simulated parser depth exhaustion"),
            ):
                with self.assertRaisesRegex(
                    Version2ReleaseReceiptError,
                    "not valid JSON",
                ):
                    read_version2_release_receipt(output)


    def test_write_rejects_active_mutated_scalar_without_comparison_or_create(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            touched: list[str] = []

            class ActiveRepository(str):
                def __eq__(self, other):
                    touched.append("eq")
                    raise AssertionError("active receipt scalar comparison executed")

                def __ne__(self, other):
                    touched.append("ne")
                    raise AssertionError("active receipt scalar comparison executed")

            object.__setattr__(
                receipt,
                "repository",
                ActiveRepository(REPOSITORY_FULL_NAME),
            )
            output = Path(td) / "receipt.json"

            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "repository identity mismatch",
            ):
                write_version2_release_receipt(output, receipt)

            self.assertEqual(touched, [])
            self.assertFalse(output.exists())

if __name__ == "__main__":
    unittest.main()
