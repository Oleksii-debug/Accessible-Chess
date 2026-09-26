from __future__ import annotations

import hashlib
import io
import json
import stat
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

from acs.sound_pack_download import HttpsZipSoundPackAcquirer
from acs.sound_pack_store import SoundPackInstallService, SoundPackStore
from acs.sound_profiles import CORE_SOUND_EVENTS, SoundPackCatalogEntry


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wav_bytes(seed: bytes) -> bytes:
    value = hashlib.sha256(seed).digest()[0]
    sample = int((value - 128) * 128).to_bytes(2, "little", signed=True)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(sample * 16)
    return buffer.getvalue()


def _pack_files(pack_id="download.test", version="1.0.0"):
    payloads = {
        event: _wav_bytes(event.encode("ascii"))
        for event in CORE_SOUND_EVENTS
    }
    files = {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS}
    manifest = {
        "schema_version": 1,
        "pack_id": pack_id,
        "version": version,
        "title": "Downloaded Test",
        "author": "Accessible Chess",
        "license_id": "CC0-1.0",
        "provenance": "https://example.invalid/source",
        "files": files,
        "sha256": {event: _digest(payload) for event, payload in payloads.items()},
    }
    archive_files = {
        "manifest.json": json.dumps(manifest).encode("utf-8"),
        **{files[event]: payload for event, payload in payloads.items()},
    }
    return archive_files


def _zip_bytes(files, *, extra_infos=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
        for info, payload in extra_infos:
            archive.writestr(info, payload)
    return buffer.getvalue()


def _entry(archive: bytes, **overrides):
    values = {
        "pack_id": "download.test",
        "version": "1.0.0",
        "title": "Downloaded Test",
        "author": "Accessible Chess",
        "license_id": "CC0-1.0",
        "provenance": "https://example.invalid/source",
        "download_url": "https://cdn.example.invalid/download-test.zip",
        "archive_sha256": _digest(archive),
        "archive_size_bytes": len(archive),
    }
    values.update(overrides)
    return SoundPackCatalogEntry(**values)


class _Response:
    def __init__(self, payload, *, final_url=None, content_length=True):
        self._stream = io.BytesIO(payload)
        self._url = final_url
        self.headers = {}
        if content_length:
            self.headers["Content-Length"] = str(len(payload))

    def read(self, size=-1):
        return self._stream.read(size)

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Opener:
    def __init__(self, payload, **response_kwargs):
        self.payload = payload
        self.response_kwargs = response_kwargs
        self.calls = []

    def __call__(self, request, *, timeout):
        self.calls.append((request, timeout))
        return _Response(self.payload, **self.response_kwargs)


class HttpsZipSoundPackAcquirerTests(unittest.TestCase):
    def test_end_to_end_download_extract_install_and_cleanup(self):
        archive = _zip_bytes(_pack_files())
        opener = _Opener(
            archive,
            final_url="https://cdn.example.invalid/download-test.zip",
        )
        acquirer = HttpsZipSoundPackAcquirer(opener=opener)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scratch = root / "scratch"
            store = SoundPackStore(root / "installed")
            service = SoundPackInstallService(
                store,
                acquirer,
                staging_parent=scratch,
            )

            manifest = service.install(_entry(archive))

            self.assertEqual(manifest.pack_id, "download.test")
            self.assertEqual(
                store.resolve("download.test", "move").read_bytes(),
                _wav_bytes(b"move"),
            )
            self.assertEqual(list(scratch.iterdir()), [])
            self.assertEqual(len(opener.calls), 1)
            request, timeout = opener.calls[0]
            self.assertEqual(
                request.full_url,
                "https://cdn.example.invalid/download-test.zip",
            )
            self.assertEqual(timeout, 30.0)

    def test_archive_digest_mismatch_fails_and_cleans_private_staging(self):
        archive = _zip_bytes(_pack_files())
        opener = _Opener(archive)
        bad = _entry(archive, archive_sha256="0" * 64)
        acquirer = HttpsZipSoundPackAcquirer(opener=opener)
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "scratch"
            with self.assertRaisesRegex(ValueError, "digest"):
                acquirer.acquire(bad, staging_parent=scratch)
            self.assertEqual(list(scratch.iterdir()), [])

    def test_catalogue_size_limit_fails_before_network(self):
        archive = _zip_bytes(_pack_files())
        opener = _Opener(archive)
        acquirer = HttpsZipSoundPackAcquirer(
            opener=opener,
            max_archive_bytes=max(1, len(archive) - 1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "size limit"):
                acquirer.acquire(_entry(archive), staging_parent=Path(tmp))
        self.assertEqual(opener.calls, [])

    def test_content_length_must_match_catalogue(self):
        archive = _zip_bytes(_pack_files())
        opener = _Opener(archive + b"x")
        entry = _entry(archive)
        acquirer = HttpsZipSoundPackAcquirer(opener=opener)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Content-Length"):
                acquirer.acquire(entry, staging_parent=Path(tmp))

    def test_https_redirect_cannot_downgrade(self):
        archive = _zip_bytes(_pack_files())
        opener = _Opener(
            archive,
            final_url="http://cdn.example.invalid/download-test.zip",
        )
        acquirer = HttpsZipSoundPackAcquirer(opener=opener)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                acquirer.acquire(_entry(archive), staging_parent=Path(tmp))

    def test_path_traversal_archive_is_rejected_without_escape(self):
        files = _pack_files()
        files["../escape.wav"] = b"RIFFescape"
        archive = _zip_bytes(files)
        opener = _Opener(archive)
        acquirer = HttpsZipSoundPackAcquirer(opener=opener)
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            with self.assertRaisesRegex(ValueError, "below staging root"):
                acquirer.acquire(_entry(archive), staging_parent=parent)
            self.assertFalse((parent / "escape.wav").exists())

    def test_executable_or_unknown_payload_is_rejected(self):
        files = _pack_files()
        files["payload.exe"] = b"MZ"
        archive = _zip_bytes(files)
        acquirer = HttpsZipSoundPackAcquirer(opener=_Opener(archive))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "unsupported payload"):
                acquirer.acquire(_entry(archive), staging_parent=Path(tmp))

    def test_symlink_member_is_rejected(self):
        files = _pack_files()
        link = zipfile.ZipInfo("audio/link.wav")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = _zip_bytes(files, extra_infos=((link, b"move.wav"),))
        acquirer = HttpsZipSoundPackAcquirer(opener=_Opener(archive))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "symlinks"):
                acquirer.acquire(_entry(archive), staging_parent=Path(tmp))

    def test_case_colliding_paths_are_rejected_before_windows_extraction(self):
        files = _pack_files()
        files["Audio/MOVE.wav"] = b"RIFFcollision"
        archive = _zip_bytes(files)
        acquirer = HttpsZipSoundPackAcquirer(opener=_Opener(archive))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "colliding"):
                acquirer.acquire(_entry(archive), staging_parent=Path(tmp))

    def test_compression_ratio_limit_rejects_zip_bomb_shape(self):
        files = _pack_files()
        files["audio/padding.wav"] = b"0" * 100000
        archive = _zip_bytes(files)
        acquirer = HttpsZipSoundPackAcquirer(
            opener=_Opener(archive),
            max_compression_ratio=5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "compression ratio"):
                acquirer.acquire(_entry(archive), staging_parent=Path(tmp))


if __name__ == "__main__":
    unittest.main()
