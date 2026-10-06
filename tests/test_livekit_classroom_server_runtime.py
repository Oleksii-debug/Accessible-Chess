from __future__ import annotations

import asyncio
from pathlib import Path
import traceback
import unittest

from acs.livekit_classroom_moderation_admin import LIVEKIT_API_VERSION
from acs.livekit_classroom_server_runtime import (
    LiveKitClassroomServerCleanupCancelled,
    LiveKitClassroomServerRuntime,
    LiveKitClassroomServerRuntimeError,
    MAX_PROVIDER_CREDENTIAL_CHARS,
    MAX_PROVIDER_ENDPOINT_CHARS,
)
SERVER_RUNTIME_WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "livekit-classroom-server-runtime.yml"
)

from tests.test_livekit_classroom_moderation_admin import (
    FakeApi as ModerationFakeApi,
    FakeRoomService,
    participant,
)


class FakeLiveKitClient:
    instances = []

    def __init__(self, url, *, api_key, api_secret):
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret
        self.room = FakeRoomService(participant(can_publish_data=True))
        self.close_calls = 0
        self.close_error = None
        type(self).instances.append(self)

    async def aclose(self):
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeApi(ModerationFakeApi):
    LiveKitAPI = FakeLiveKitClient


class LiveKitClassroomServerRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeLiveKitClient.instances.clear()

    async def open(self, **overrides):
        values = {
            "endpoint": "https://classroom.example.invalid",
            "api_key": "server-key",
            "api_secret": "server-secret",
            "api_module": FakeApi,
            "sdk_version": LIVEKIT_API_VERSION,
        }
        values.update(overrides)
        return await LiveKitClassroomServerRuntime.open(**values)

    async def test_explicit_backend_configuration_builds_one_client_and_adapter(self):
        runtime = await self.open()
        self.assertEqual(len(FakeLiveKitClient.instances), 1)
        client = FakeLiveKitClient.instances[0]
        self.assertEqual(client.url, "https://classroom.example.invalid")
        self.assertEqual(client.api_key, "server-key")
        self.assertEqual(client.api_secret, "server-secret")
        self.assertIsNotNone(runtime.moderation_admin)
        self.assertTrue(
            callable(
                getattr(
                    runtime.moderation_admin,
                    "moderation_effect_matches",
                    None,
                )
            )
        )
        self.assertFalse(runtime.closed)
        await runtime.aclose()
        self.assertTrue(runtime.closed)
        self.assertEqual(client.close_calls, 1)

    async def test_trailing_root_slash_is_normalized_without_other_url_rewrite(self):
        runtime = await self.open(endpoint="https://classroom.example.invalid/")
        client = FakeLiveKitClient.instances[-1]
        self.assertEqual(client.url, "https://classroom.example.invalid")
        await runtime.aclose()

    async def test_local_plain_http_is_allowed_only_for_loopback_development(self):
        for endpoint in (
            "http://127.0.0.1:7880",
            "http://127.0.0.42:7880",
            "http://[::1]:7880",
        ):
            with self.subTest(endpoint=endpoint):
                runtime = await self.open(endpoint=endpoint)
                self.assertEqual(FakeLiveKitClient.instances[-1].url, endpoint)
                await runtime.aclose()

        before = len(FakeLiveKitClient.instances)
        for endpoint in (
            "http://localhost:7880",
            "http://classroom.example.invalid",
            "http://10.0.0.4:7880",
            "http://192.168.1.10:7880",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(
                    LiveKitClassroomServerRuntimeError,
                    "must use HTTPS",
                ):
                    await self.open(endpoint=endpoint)
        self.assertEqual(len(FakeLiveKitClient.instances), before)

    async def test_endpoint_rejects_credentials_paths_query_fragment_and_wrong_schemes(self):
        invalid = (
            "",
            " https://classroom.example.invalid",
            "https://classroom.example.invalid ",
            "https://user:password@classroom.example.invalid",
            "https://classroom.example.invalid/api",
            "https://classroom.example.invalid?secret=value",
            "https://classroom.example.invalid#fragment",
            "ws://classroom.example.invalid",
            "wss://classroom.example.invalid",
            "file:///tmp/livekit",
            "https://classroom.example.invalid:",
            "https://",
            "not-a-url",
            "https://classroom.example.invalid\n",
            "https://class room.example.invalid",
            "https://classroom.example.invalid\t",
            "https://classroom.example.invalid:0",
            "https://classroom.example.invalid/" + ("x" * MAX_PROVIDER_ENDPOINT_CHARS),
        )
        for endpoint in invalid:
            with self.subTest(endpoint=repr(endpoint)[:80]):
                with self.assertRaises(LiveKitClassroomServerRuntimeError):
                    await self.open(endpoint=endpoint)
        self.assertEqual(FakeLiveKitClient.instances, [])

    async def test_credentials_are_explicit_strict_and_bounded(self):
        invalid_pairs = (
            ("", "secret"),
            (" key", "secret"),
            ("key ", "secret"),
            ("key\n", "secret"),
            ("key\tpart", "secret"),
            ("key", ""),
            ("key", " secret"),
            ("key", "secret\r"),
            ("key", "secret\tpart"),
            ("k" * (MAX_PROVIDER_CREDENTIAL_CHARS + 1), "secret"),
            ("key", "s" * (MAX_PROVIDER_CREDENTIAL_CHARS + 1)),
        )
        for key, secret in invalid_pairs:
            with self.subTest(key=repr(key)[:30], secret=repr(secret)[:30]):
                with self.assertRaises(LiveKitClassroomServerRuntimeError):
                    await self.open(api_key=key, api_secret=secret)
        self.assertEqual(FakeLiveKitClient.instances, [])

    async def test_sdk_version_is_fail_closed_before_provider_client_construction(self):
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "version is not approved",
        ):
            await self.open(sdk_version="1.2.0")
        self.assertEqual(FakeLiveKitClient.instances, [])

    async def test_incompatible_room_service_closes_new_client_before_failing(self):
        class BadClient(FakeLiveKitClient):
            instances = []

            def __init__(self, url, *, api_key, api_secret):
                super().__init__(url, api_key=api_key, api_secret=api_secret)
                self.room = object()

        class BadApi(ModerationFakeApi):
            LiveKitAPI = BadClient

        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "^LiveKit server runtime initialization failed$",
        ):
            await self.open(
                api_module=BadApi,
                sdk_version=LIVEKIT_API_VERSION,
            )

        self.assertEqual(len(BadClient.instances), 1)
        self.assertEqual(BadClient.instances[0].close_calls, 1)

    async def test_initialization_failure_with_failed_cleanup_retains_retryable_owner(self):
        secret = "initial-cleanup-secret"

        class BadClient(FakeLiveKitClient):
            instances = []

            def __init__(self, url, *, api_key, api_secret):
                super().__init__(url, api_key=api_key, api_secret=api_secret)
                self.room = object()

            async def aclose(self):
                self.close_calls += 1
                if self.close_calls == 1:
                    raise RuntimeError(secret)

        class BadApi(ModerationFakeApi):
            LiveKitAPI = BadClient

        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "^LiveKit server runtime initialization failed$",
        ) as caught:
            await self.open(
                api_module=BadApi,
                sdk_version=LIVEKIT_API_VERSION,
                api_secret=secret,
            )

        error = caught.exception
        self.assertIsNone(error.__cause__)
        self.assertNotIn(secret, "".join(traceback.format_exception(error)))
        cleanup = error.cleanup_runtime
        self.assertIsNotNone(cleanup)
        self.assertIn("state='cleanup_required'", repr(cleanup))
        self.assertNotIn(secret, repr(cleanup))
        self.assertFalse(cleanup.closed)
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "requires cleanup",
        ):
            _ = cleanup.moderation_admin
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "requires cleanup",
        ):
            await cleanup.__aenter__()

        client = BadClient.instances[0]
        self.assertEqual(client.close_calls, 1)
        await cleanup.aclose()
        self.assertEqual(client.close_calls, 2)
        self.assertTrue(cleanup.closed)
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "runtime is closed",
        ):
            _ = cleanup.moderation_admin

    async def test_cancelled_initialization_cleanup_preserves_retryable_owner(self):
        cleanup_started = asyncio.Event()

        class BadClient(FakeLiveKitClient):
            instances = []

            def __init__(self, url, *, api_key, api_secret):
                super().__init__(url, api_key=api_key, api_secret=api_secret)
                self.room = object()

            async def aclose(self):
                self.close_calls += 1
                if self.close_calls == 1:
                    cleanup_started.set()
                    await asyncio.Future()

        class BadApi(ModerationFakeApi):
            LiveKitAPI = BadClient

        opening = asyncio.create_task(
            self.open(
                api_module=BadApi,
                sdk_version=LIVEKIT_API_VERSION,
            )
        )
        await cleanup_started.wait()
        opening.cancel()
        with self.assertRaises(LiveKitClassroomServerCleanupCancelled) as caught:
            await opening

        cleanup = caught.exception.cleanup_runtime
        self.assertFalse(cleanup.closed)
        self.assertIn("state='cleanup_required'", repr(cleanup))
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "requires cleanup",
        ):
            _ = cleanup.moderation_admin

        client = BadClient.instances[0]
        self.assertEqual(client.close_calls, 1)
        await cleanup.aclose()
        self.assertEqual(client.close_calls, 2)
        self.assertTrue(cleanup.closed)

    async def test_successful_initialization_cleanup_does_not_publish_cleanup_owner(self):
        class BadClient(FakeLiveKitClient):
            instances = []

            def __init__(self, url, *, api_key, api_secret):
                super().__init__(url, api_key=api_key, api_secret=api_secret)
                self.room = object()

        class BadApi(ModerationFakeApi):
            LiveKitAPI = BadClient

        with self.assertRaises(LiveKitClassroomServerRuntimeError) as caught:
            await self.open(
                api_module=BadApi,
                sdk_version=LIVEKIT_API_VERSION,
            )

        self.assertIsNone(caught.exception.cleanup_runtime)
        self.assertEqual(BadClient.instances[0].close_calls, 1)

    async def test_missing_provider_close_api_retains_quarantined_cleanup_owner(self):
        class NoCloseClient:
            instances = []

            def __init__(self, url, *, api_key, api_secret):
                self.url = url
                self.api_key = api_key
                self.api_secret = api_secret
                self.room = FakeRoomService(participant(can_publish_data=True))
                type(self).instances.append(self)

        class NoCloseApi(ModerationFakeApi):
            LiveKitAPI = NoCloseClient

        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "lifecycle API is unavailable",
        ) as caught:
            await self.open(
                api_module=NoCloseApi,
                sdk_version=LIVEKIT_API_VERSION,
            )

        cleanup = caught.exception.cleanup_runtime
        self.assertIsNotNone(cleanup)
        self.assertIn("state='cleanup_required'", repr(cleanup))
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "lifecycle API is unavailable",
        ):
            await cleanup.aclose()
        self.assertFalse(cleanup.closed)
        self.assertIn("state='cleanup_required'", repr(cleanup))
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "requires cleanup",
        ):
            _ = cleanup.moderation_admin

    async def test_provider_constructor_failure_is_sanitized(self):
        secret = "provider-constructor-secret"

        class BrokenClient:
            def __init__(self, *args, **kwargs):
                raise RuntimeError(secret)

        class BrokenApi(ModerationFakeApi):
            LiveKitAPI = BrokenClient

        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "^LiveKit server runtime initialization failed$",
        ) as caught:
            await self.open(
                api_module=BrokenApi,
                sdk_version=LIVEKIT_API_VERSION,
                api_secret=secret,
            )
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))
        self.assertIsNone(caught.exception.__cause__)

    async def test_ordinary_runtime_errors_do_not_expose_cleanup_owner(self):
        runtime = await self.open()
        client = FakeLiveKitClient.instances[-1]
        client.close_error = RuntimeError("close-detail")
        with self.assertRaises(LiveKitClassroomServerRuntimeError) as caught:
            await runtime.aclose()
        self.assertIsNone(caught.exception.cleanup_runtime)
        client.close_error = None
        await runtime.aclose()

    async def test_close_is_idempotent_and_closed_runtime_hides_adapter(self):
        runtime = await self.open()
        client = FakeLiveKitClient.instances[-1]
        await runtime.aclose()
        await runtime.aclose()
        self.assertEqual(client.close_calls, 1)
        self.assertTrue(runtime.closed)
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "runtime is closed",
        ):
            _ = runtime.moderation_admin
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "runtime is closed",
        ):
            await runtime.__aenter__()

    async def test_close_failure_is_sanitized_and_retry_keeps_cleanup_authority(self):
        secret = "provider-close-secret"
        runtime = await self.open()
        client = FakeLiveKitClient.instances[-1]
        client.close_error = RuntimeError(secret)

        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "^LiveKit server runtime close failed$",
        ) as caught:
            await runtime.aclose()

        self.assertFalse(runtime.closed)
        self.assertEqual(client.close_calls, 1)
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))
        self.assertIsNone(caught.exception.__cause__)
        self.assertIn("state='cleanup_required'", repr(runtime))
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "requires cleanup",
        ):
            _ = runtime.moderation_admin
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "requires cleanup",
        ):
            await runtime.__aenter__()

        client.close_error = None
        await runtime.aclose()

        self.assertTrue(runtime.closed)
        self.assertEqual(client.close_calls, 2)
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "runtime is closed",
        ):
            _ = runtime.moderation_admin

    async def test_cancelled_close_latches_cleanup_only_until_retry_succeeds(self):
        close_started = asyncio.Event()

        class CancellableClient(FakeLiveKitClient):
            instances = []

            async def aclose(self):
                self.close_calls += 1
                if self.close_calls == 1:
                    close_started.set()
                    await asyncio.Future()

        class CancellableApi(ModerationFakeApi):
            LiveKitAPI = CancellableClient

        runtime = await self.open(
            api_module=CancellableApi,
            sdk_version=LIVEKIT_API_VERSION,
        )
        client = CancellableClient.instances[-1]
        closing = asyncio.create_task(runtime.aclose())
        await close_started.wait()
        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing

        self.assertFalse(runtime.closed)
        self.assertEqual(client.close_calls, 1)
        self.assertIn("state='cleanup_required'", repr(runtime))
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "requires cleanup",
        ):
            _ = runtime.moderation_admin

        await runtime.aclose()
        self.assertTrue(runtime.closed)
        self.assertEqual(client.close_calls, 2)

    async def test_close_in_progress_blocks_use_and_parallel_shutdown(self):
        close_started = asyncio.Event()
        allow_close = asyncio.Event()

        class SlowClient(FakeLiveKitClient):
            instances = []

            async def aclose(self):
                self.close_calls += 1
                close_started.set()
                await allow_close.wait()

        class SlowApi(ModerationFakeApi):
            LiveKitAPI = SlowClient

        runtime = await self.open(
            api_module=SlowApi,
            sdk_version=LIVEKIT_API_VERSION,
        )
        client = SlowClient.instances[-1]
        closing = asyncio.create_task(runtime.aclose())
        await close_started.wait()

        self.assertFalse(runtime.closed)
        self.assertIn("state='closing'", repr(runtime))
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "runtime is closing",
        ):
            _ = runtime.moderation_admin
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "already in progress",
        ):
            await runtime.aclose()
        with self.assertRaisesRegex(
            LiveKitClassroomServerRuntimeError,
            "runtime is closing",
        ):
            await runtime.__aenter__()
        self.assertEqual(client.close_calls, 1)

        allow_close.set()
        await closing

        self.assertTrue(runtime.closed)
        self.assertEqual(client.close_calls, 1)

    async def test_async_context_manager_closes_exactly_once(self):
        runtime = await self.open()
        client = FakeLiveKitClient.instances[-1]
        async with runtime as entered:
            self.assertIs(entered, runtime)
            self.assertIsNotNone(entered.moderation_admin)
        self.assertTrue(runtime.closed)
        self.assertEqual(client.close_calls, 1)

    async def test_workflow_scope_uses_immutable_pull_request_base(self):
        workflow = SERVER_RUNTIME_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn(
            'git diff --name-only "$EVENT_BASE_SHA...HEAD"',
            workflow,
        )
        self.assertIn(
            'git diff --check "$EVENT_BASE_SHA...HEAD"',
            workflow,
        )
        self.assertNotIn("refs/remotes/origin/$EXPECTED_BASE_REF", workflow)

    async def test_repr_redacts_endpoint_and_credentials(self):
        endpoint = "https://secret-classroom.example.invalid"
        key = "private-api-key"
        secret = "private-api-secret"
        runtime = await self.open(
            endpoint=endpoint,
            api_key=key,
            api_secret=secret,
        )
        rendered = repr(runtime)
        self.assertNotIn(endpoint, rendered)
        self.assertNotIn(key, rendered)
        self.assertNotIn(secret, rendered)
        self.assertIn(LIVEKIT_API_VERSION, rendered)
        await runtime.aclose()


if __name__ == "__main__":
    unittest.main()
