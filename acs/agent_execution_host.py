from __future__ import annotations

"""Production execution host for the Universal Chess Agent conversation surface.

The model/tool loop runs on one dedicated non-daemon asyncio thread so provider
latency never blocks the Windows UI. Canonical application operations stay on
the native owner thread through the injected owner-call boundary; this module
does not create a second Board, GameTree, ACSDB, parser, or chess-rules owner.
"""

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from math import isfinite
import threading
from typing import Any

from .agent_webview_projection import AgentConversationProjection
from .universal_chess_agent import UniversalChessAgentRuntime


OwnerThreadCall = Callable[[Callable[[], object]], Awaitable[object]]


class AgentOwnerThreadCall:
    """Adapt an existing synchronous owner-thread marshal to an async tool port."""

    def __init__(self, invoke_owner: Callable[[Callable[[], object]], object]) -> None:
        if not callable(invoke_owner):
            raise TypeError("invoke_owner must be callable")
        self._invoke_owner = invoke_owner

    async def __call__(self, callback: Callable[[], object]) -> object:
        if not callable(callback):
            raise TypeError("owner callback must be callable")
        return self._invoke_owner(callback)


class AgentConversationRuntimeHost:
    """Run one canonical UniversalChessAgentRuntime off the Windows UI thread."""

    def __init__(
        self,
        *,
        runtime: UniversalChessAgentRuntime,
        projection: AgentConversationProjection,
        thread_name: str = "AccessibleChessAgent",
    ) -> None:
        if type(runtime) is not UniversalChessAgentRuntime:
            raise TypeError("runtime must be UniversalChessAgentRuntime")
        if type(projection) is not AgentConversationProjection:
            raise TypeError("projection must be AgentConversationProjection")
        if type(thread_name) is not str or not thread_name.strip() or len(thread_name) > 80:
            raise ValueError("thread_name must be bounded non-empty text")

        self.runtime = runtime
        self.projection = projection
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._startup_error: BaseException | None = None
        self._runs: dict[str, Future[Any]] = {}
        self._closed = False
        self._stop_requested = False
        self._thread = threading.Thread(
            target=self._thread_main,
            name=thread_name.strip(),
            daemon=False,
        )
        self._thread.start()
        if not self._ready.wait(5.0):
            self._closed = True
            raise RuntimeError("Agent execution host did not start")
        if self._startup_error is not None or self._loop is None:
            self._closed = True
            raise RuntimeError("Agent execution host could not start") from self._startup_error

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def _thread_main(self) -> None:
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            with self._lock:
                self._loop = loop
            self._ready.set()
            loop.run_forever()
        except BaseException as error:
            with self._lock:
                self._startup_error = error
            self._ready.set()
        finally:
            if loop is not None and not loop.is_closed():
                try:
                    pending = tuple(asyncio.all_tasks(loop))
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                finally:
                    loop.close()
            with self._lock:
                self._loop = None

    @staticmethod
    def _canonical_run_id(value: object) -> str:
        if type(value) is not str:
            raise TypeError("Agent run id must be text")
        token = value.strip()
        if not token or token != value or len(token) > 180 or "\x00" in token:
            raise ValueError("Agent run id is invalid")
        return token

    @staticmethod
    def _canonical_prompt(value: object) -> str:
        if type(value) is not str:
            raise TypeError("Agent prompt must be text")
        text = value.strip()
        if not text or len(text) > 8_000 or "\x00" in text:
            raise ValueError("Agent prompt is invalid")
        return text

    def start_run(self, run_id: str, user_text: str) -> None:
        """Schedule one UI-created run identity without blocking the caller."""

        token = self._canonical_run_id(run_id)
        prompt = self._canonical_prompt(user_text)
        with self._lock:
            if self._closed:
                raise RuntimeError("Agent execution host is closed")
            loop = self._loop
            if loop is None or not self._thread.is_alive():
                raise RuntimeError("Agent execution host is unavailable")
            existing = self._runs.get(token)
            if existing is not None and not existing.done():
                raise RuntimeError("Agent run is already scheduled")
            future = asyncio.run_coroutine_threadsafe(
                self._execute(token, prompt),
                loop,
            )
            self._runs[token] = future
            future.add_done_callback(
                lambda completed, identity=token: self._run_finished(identity, completed)
            )

    async def _execute(self, run_id: str, user_text: str) -> None:
        self.projection.update_runtime_status(
            run_id,
            {
                "provider_id": self.runtime.provider_id,
                "model": self.runtime.model or "",
                "steps": 0,
                "model_calls": 0,
                "tool_calls": 0,
            },
        )
        try:
            result = await self.runtime.run(run_id=run_id, user_text=user_text)
        except asyncio.CancelledError:
            self.projection.mark_cancelled(run_id)
            raise
        except BaseException:
            self.projection.fail(run_id)
            return
        self.projection.complete_result(run_id, result)

    def _run_finished(self, run_id: str, future: Future[Any]) -> None:
        with self._lock:
            if self._runs.get(run_id) is future:
                self._runs.pop(run_id, None)
        if future.cancelled():
            self.projection.mark_cancelled(run_id)

    def cancel_run(self, run_id: str) -> None:
        """Request cancellation without waiting on the UI/browser caller."""

        token = self._canonical_run_id(run_id)
        with self._lock:
            if self._closed:
                raise RuntimeError("Agent execution host is closed")
            future = self._runs.get(token)
        if future is None:
            self.projection.mark_cancelled(token)
            return
        future.cancel()

    @staticmethod
    def _timeout(value: float | None) -> float | None:
        if value is None:
            return None
        if type(value) not in (int, float):
            raise TypeError("Agent shutdown timeout must be numeric or None")
        timeout = float(value)
        if not isfinite(timeout) or timeout < 0:
            raise ValueError("Agent shutdown timeout must be finite and non-negative")
        return timeout

    def _request_loop_stop(self) -> None:
        with self._lock:
            loop = self._loop
            if loop is None or self._stop_requested:
                return
            self._stop_requested = True

        def schedule_stop() -> None:
            async def cancel_then_stop() -> None:
                current = asyncio.current_task()
                tasks = tuple(
                    task
                    for task in asyncio.all_tasks()
                    if task is not current and not task.done()
                )
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                loop.stop()

            asyncio.create_task(cancel_then_stop())

        loop.call_soon_threadsafe(schedule_stop)

    def shutdown(self, timeout: float | None = None) -> bool:
        """Cancel Agent work and join its non-daemon thread before DB teardown."""

        wait = self._timeout(timeout)
        with self._lock:
            self._closed = True
            run_ids = tuple(self._runs)
            futures = tuple(self._runs.values())
        for future in futures:
            future.cancel()
        self._request_loop_stop()
        self._thread.join(wait)
        if self._thread.is_alive():
            return False
        for run_id in run_ids:
            self.projection.mark_cancelled(run_id)
        return True


def bind_agent_runtime(
    application: object,
    runtime: UniversalChessAgentRuntime,
) -> AgentConversationRuntimeHost:
    """Bind a canonical Agent runtime to the final-product conversation surface."""

    if type(runtime) is not UniversalChessAgentRuntime:
        raise TypeError("runtime must be UniversalChessAgentRuntime")
    assert_thread = getattr(application, "_assert_thread", None)
    bind = getattr(application, "bind_agent_conversation", None)
    unbind = getattr(application, "unbind_agent_conversation", None)
    install = getattr(application, "install_agent_execution_host", None)
    if not callable(assert_thread) or not callable(bind) or not callable(unbind):
        raise TypeError("application does not expose the Agent host contract")
    if not callable(install):
        raise TypeError("application cannot own Agent host shutdown")
    assert_thread()

    holder: dict[str, AgentConversationRuntimeHost] = {}

    def start(run_id: str, text: str) -> None:
        host = holder.get("host")
        if host is None:
            raise RuntimeError("Agent execution host is not ready")
        host.start_run(run_id, text)

    def cancel(run_id: str) -> None:
        host = holder.get("host")
        if host is None:
            raise RuntimeError("Agent execution host is not ready")
        host.cancel_run(run_id)

    projection = bind(start_run=start, cancel_run=cancel)
    host: AgentConversationRuntimeHost | None = None
    try:
        host = AgentConversationRuntimeHost(runtime=runtime, projection=projection)
        holder["host"] = host
        install(host)
        return host
    except BaseException:
        if host is not None:
            try:
                host.shutdown(timeout=5.0)
            except BaseException:
                pass
        try:
            unbind()
        except BaseException:
            pass
        raise


__all__ = [
    "AgentConversationRuntimeHost",
    "AgentOwnerThreadCall",
    "OwnerThreadCall",
    "bind_agent_runtime",
]
