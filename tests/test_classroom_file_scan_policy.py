from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.classroom_collaboration import FileQuotaPolicy, _canonical_object_key
from acs.classroom_collaboration_storage import AttachmentMetadata
from acs.classroom_file_scan_policy import (
    ClassroomFileMimePolicy,
    ClassroomFilePolicyScanner,
)
from acs.classroom_file_server import (
    ClassroomFileServerSQLiteStore,
    ClassroomFileServerService,
)


class RecordingMalwareScanner:
    def __init__(self, *, state: str = "clean", fail: bool = False) -> None:
        self.state = state
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def scan(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.fail:
            raise RuntimeError("private scanner endpoint C:/secret/provider")
        return self.state


class AllowAuthorization:
    def authorize_file_action(self, **_kwargs):
        return True


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[str] = []

    def stored_sha256(self, *, object_key: str):
        content = self.objects.get(object_key)
        return None if content is None else hashlib.sha256(content).hexdigest()

    def put(self, *, object_key: str, content: bytes, expected_sha256: str):
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise RuntimeError("hash mismatch")
        self.put_calls.append(object_key)
        self.objects[object_key] = bytes(content)

    def issue_read_token(self, *, object_key: str, participant_id: str, ttl_seconds: int):
        if object_key not in self.objects:
            raise RuntimeError("object missing")
        return "short-lived-read-token"

    def delete(self, *, object_key: str):
        self.objects.pop(object_key, None)


def scan_kwargs(mime_type: str | None = "text/plain") -> dict[str, object]:
    content = b"opaque classroom bytes"
    return {
        "room_id": "room-1",
        "sender_id": "student-1",
        "display_name": "lesson.txt",
        "mime_type": mime_type,
        "sha256": hashlib.sha256(content).hexdigest(),
        "content": content,
    }


class ClassroomFileMimePolicyTests(unittest.TestCase):
    def test_allow_deny_wildcards_are_canonical_and_deny_wins(self) -> None:
        policy = ClassroomFileMimePolicy(
            allowed=("TEXT/*", "application/pdf", "text/*"),
            denied=("text/html", "application/x-msdownload"),
        )

        self.assertEqual(policy.allowed, ("text/*", "application/pdf"))
        self.assertTrue(policy.allows("text/plain"))
        self.assertTrue(policy.allows("Text/Plain; charset=UTF-8"))
        self.assertTrue(policy.allows("application/pdf"))
        self.assertFalse(policy.allows("text/html"))
        self.assertFalse(policy.allows("application/json"))
        self.assertFalse(policy.allows("text"))
        self.assertFalse(policy.allows("text/pl*ain"))

        deny_all = ClassroomFileMimePolicy(denied=("*/*",))
        self.assertFalse(deny_all.allows("application/pdf"))

    def test_missing_mime_policy_is_explicit_and_allow_list_fails_closed(self) -> None:
        self.assertTrue(ClassroomFileMimePolicy().allows(None))
        self.assertTrue(ClassroomFileMimePolicy().allows(""))
        self.assertFalse(
            ClassroomFileMimePolicy(allow_missing=False).allows(None)
        )
        self.assertFalse(
            ClassroomFileMimePolicy(allowed=("text/*",)).allows(None)
        )
        self.assertFalse(
            ClassroomFileMimePolicy(allowed=()).allows("text/plain")
        )

    def test_policy_patterns_are_bounded_and_wildcard_segments_are_strict(self) -> None:
        with self.assertRaises(TypeError):
            ClassroomFileMimePolicy(allowed=["text/plain"])
        for pattern in ("*/plain", "text/pl*ain", "text/plain; charset=utf-8", ""):
            with self.subTest(pattern=pattern):
                with self.assertRaises(ValueError):
                    ClassroomFileMimePolicy(allowed=(pattern,))
        with self.assertRaises(ValueError):
            ClassroomFileMimePolicy(
                denied=tuple(f"application/x-{index}" for index in range(257))
            )
        with self.assertRaises(TypeError):
            ClassroomFileMimePolicy(allow_missing=1)

    def test_denied_mime_never_crosses_malware_scanner(self) -> None:
        malware = RecordingMalwareScanner()
        scanner = ClassroomFilePolicyScanner(
            policy=ClassroomFileMimePolicy(denied=("application/*",)),
            malware_scanner=malware,
        )

        result = scanner.scan(**scan_kwargs("application/pdf"))

        self.assertEqual(result, "blocked")
        self.assertEqual(malware.calls, [])

    def test_allowed_mime_crosses_malware_scanner_exactly_once(self) -> None:
        malware = RecordingMalwareScanner()
        scanner = ClassroomFilePolicyScanner(
            policy=ClassroomFileMimePolicy(
                allowed=("text/*",),
                denied=("text/html",),
            ),
            malware_scanner=malware,
        )
        values = scan_kwargs("text/plain; charset=utf-8")

        result = scanner.scan(**values)

        self.assertEqual(result, "clean")
        self.assertEqual(malware.calls, [values])
        self.assertNotIn("opaque classroom bytes", repr(scanner))
        self.assertEqual(
            repr(scanner),
            "ClassroomFilePolicyScanner(policy=<bound>, malware_scanner=<bound>)",
        )

    def test_malware_failure_and_invalid_result_fail_closed_without_detail(self) -> None:
        failed = ClassroomFilePolicyScanner(
            policy=ClassroomFileMimePolicy(),
            malware_scanner=RecordingMalwareScanner(fail=True),
        )
        self.assertEqual(failed.scan(**scan_kwargs()), "failed")

        invalid = ClassroomFilePolicyScanner(
            policy=ClassroomFileMimePolicy(),
            malware_scanner=RecordingMalwareScanner(state="maybe"),
        )
        self.assertEqual(invalid.scan(**scan_kwargs()), "failed")

    def test_server_enforces_mime_policy_before_object_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            malware = RecordingMalwareScanner()
            scanner = ClassroomFilePolicyScanner(
                policy=ClassroomFileMimePolicy(
                    allowed=("text/*",),
                    denied=("text/html",),
                    allow_missing=False,
                ),
                malware_scanner=malware,
            )
            objects = MemoryObjectStore()
            service = ClassroomFileServerService(
                store=ClassroomFileServerSQLiteStore(str(root / "files.sqlite3")),
                authorization=AllowAuthorization(),
                scanner=scanner,
                object_store=objects,
                quota=FileQuotaPolicy(max_file_bytes=1024, max_room_bytes=4096),
            )
            content = b"MZ not actually executable but MIME policy is authoritative metadata gate"
            metadata = AttachmentMetadata(
                "mime-blocked-a0",
                "room-1",
                "student-1",
                77,
                "blocked.exe",
                "application/x-msdownload",
                len(content),
                hashlib.sha256(content).hexdigest(),
                _canonical_object_key("room-1", "mime-blocked-a0"),
                "uploading",
                "persistent",
                "pending",
            )

            result = service.upload(
                trusted_caller_identity="student-1",
                metadata=metadata,
                content=content,
            )

            self.assertEqual(result.transfer_state, "failed")
            self.assertEqual(result.scan_state, "blocked")
            self.assertEqual(malware.calls, [])
            self.assertEqual(objects.put_calls, [])
            self.assertEqual(objects.objects, {})

    def test_server_passes_declared_mime_to_policy_and_malware_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            malware = RecordingMalwareScanner()
            scanner = ClassroomFilePolicyScanner(
                policy=ClassroomFileMimePolicy(allowed=("text/*",)),
                malware_scanner=malware,
            )
            objects = MemoryObjectStore()
            service = ClassroomFileServerService(
                store=ClassroomFileServerSQLiteStore(str(root / "files.sqlite3")),
                authorization=AllowAuthorization(),
                scanner=scanner,
                object_store=objects,
                quota=FileQuotaPolicy(max_file_bytes=1024, max_room_bytes=4096),
            )
            content = b"plain text body"
            digest = hashlib.sha256(content).hexdigest()
            metadata = AttachmentMetadata(
                "mime-clean-a0",
                "room-1",
                "student-1",
                88,
                "lesson.txt",
                "text/plain; charset=utf-8",
                len(content),
                digest,
                _canonical_object_key("room-1", "mime-clean-a0"),
                "uploading",
                "session",
                "pending",
            )

            result = service.upload(
                trusted_caller_identity="student-1",
                metadata=metadata,
                content=content,
            )

            self.assertEqual(result.transfer_state, "stored")
            self.assertEqual(result.scan_state, "clean")
            self.assertEqual(len(malware.calls), 1)
            self.assertEqual(
                malware.calls[0]["mime_type"],
                "text/plain; charset=utf-8",
            )
            self.assertEqual(objects.objects[result.object_key], content)


if __name__ == "__main__":
    unittest.main()
