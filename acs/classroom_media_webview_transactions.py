from __future__ import annotations

"""Transactional WebView owner for packaged classroom media provider execution.

This module composes already-owned classroom media authorities.  It does not
authorize classroom actions, mint credentials, implement LiveKit, or own chess
state.  Browser actions are prepared through the shipping binder, the browser
executes the already-packaged LiveKit adapter, and canonical controller state is
committed only after exact provider acknowledgement.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import ipaddress
import re
from urllib.parse import urlsplit

from .classroom_media_host_transactions import MediaHostRecoveryRequired
from .classroom_media_provider_binder import ClassroomMediaProviderBinder
from .classroom_media_provider_execution import (
    MediaProviderExecutionError,
    MediaProviderExecutionLease,
)
from .classroom_media_webview_projection import (
    ClassroomMediaWebViewEvent,
    ClassroomMediaWebViewProjection,
)
from .classroom_realtime_media import JoinCredential, MediaSource


_MAX_PROVIDER_URL_CHARS = 2048
_MAX_PROVIDER_PAYLOAD_FIELDS = 10
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TRANSACTION_RE = re.compile(r"^(?:host|session)-[0-9a-f]{32}$")


@dataclass(frozen=True, slots=True)
class ClassroomMediaBrowserProviderConfig:
    """Non-secret browser configuration for the packaged LiveKit adapter."""

    server_url: str
    moderation_participant_identity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "server_url", _provider_url(self.server_url))
        object.__setattr__(
            self,
            "moderation_participant_identity",
            _identifier(
                self.moderation_participant_identity,
                "moderation participant identity",
            ),
        )

    def browser_payload(self) -> dict[str, str]:
        return {
            "server_url": self.server_url,
            "moderation_participant_identity": self.moderation_participant_identity,
        }


class ClassroomMediaTransactionalWebView:
    """Prepare browser provider work and reconcile it through one global binder."""

    def __init__(
        self,
        projection: ClassroomMediaWebViewProjection,
        binder: ClassroomMediaProviderBinder,
        provider_config: ClassroomMediaBrowserProviderConfig,
    ) -> None:
        if not isinstance(projection, ClassroomMediaWebViewProjection):
            raise TypeError("media transactional projection is invalid")
        if not isinstance(binder, ClassroomMediaProviderBinder):
            raise TypeError("media transactional binder is invalid")
        if not isinstance(provider_config, ClassroomMediaBrowserProviderConfig):
            raise TypeError("media browser provider config is invalid")
        host_owner = getattr(binder, "_host", None)
        if getattr(host_owner, "_controller", None) is not projection.controller:
            raise ValueError(
                "media transactional binder must own the projection controller"
            )
        self._projection = projection
        self._binder = binder
        self._provider_config = provider_config
        self._focus_by_transaction: dict[str, str] = {}

    @property
    def projection(self) -> ClassroomMediaWebViewProjection:
        return self._projection

    @property
    def binder(self) -> ClassroomMediaProviderBinder:
        return self._binder

    @property
    def provider_config(self) -> ClassroomMediaBrowserProviderConfig:
        return self._provider_config

    def __repr__(self) -> str:
        state = "recovery" if self._binder.recovery_status is not None else (
            "active" if self._binder.active_lease is not None else "idle"
        )
        return (
            "ClassroomMediaTransactionalWebView("
            f"state={state!r}, provider_url=<redacted>, credential=<redacted>)"
        )

    def _focus(self, transaction_id: str) -> str:
        return self._focus_by_transaction.get(transaction_id, "")

    def _forget(self, transaction_id: str) -> str:
        return self._focus_by_transaction.pop(transaction_id, "")

    def _dispatch_event(
        self,
        lease: MediaProviderExecutionLease | None,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        if lease is None:
            return self._projection.updated_event(focus_target=focus_target)
        transaction_id = lease.transaction_id
        if transaction_id is None:
            raise MediaProviderExecutionError(
                "prepared media provider lease has no transaction identity"
            )
        transaction_id = _transaction_id(transaction_id)
        try:
            provider = self._binder.pending_browser_payload(transaction_id)
        except Exception:
            # No browser/provider call has been published yet. Retire the exact
            # prepared transaction instead of returning an error while leaving
            # the sole provider lease stranded active.
            try:
                self._binder.provider_not_started(transaction_id)
            except MediaHostRecoveryRequired:
                return self._recovery_event(
                    transaction_id,
                    focus_target=focus_target,
                )
            except Exception:
                pass
            return self._safe_error(focus_target=focus_target)
        self._focus_by_transaction[transaction_id] = focus_target
        return ClassroomMediaWebViewEvent(
            "provider-dispatch",
            {
                "transaction_id": transaction_id,
                "provider": dict(provider),
                "provider_boundary_crossed": lease.provider_boundary_crossed,
                "focus_target": focus_target,
            },
        )

    def _recovery_event(
        self,
        transaction_id: str,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        stored_focus = self._forget(transaction_id)
        focus = focus_target or stored_focus
        base = self._projection.error_event(focus_target=focus)
        payload = dict(base.payload)
        # Explicitly retire the current media snapshot. The existing WebView
        # surface treats a present snapshot field as an instruction to replace
        # its controls; None plus recovery_required renders the fail-closed
        # recovery status immediately instead of leaving stale microphone or
        # moderation buttons active after an ambiguous provider outcome.
        payload["snapshot"] = None
        payload["recovery_required"] = True
        payload["transaction_id"] = transaction_id
        return ClassroomMediaWebViewEvent("error", payload)

    def _safe_error(
        self,
        transaction_id: str = "",
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        focus = focus_target or (
            self._focus(transaction_id) if transaction_id else ""
        )
        return self._projection.error_event(focus_target=focus)

    def _mutation_error(
        self,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        """Preserve a recovery latch created while preparing a browser mutation."""

        recovery = self._binder.recovery_status
        if recovery is not None and recovery.lease.transaction_id is not None:
            return self._recovery_event(
                recovery.lease.transaction_id,
                focus_target=focus_target,
            )
        return self._safe_error(focus_target=focus_target)

    def _provider_callback_error(
        self,
        transaction_id: str = "",
    ) -> ClassroomMediaWebViewEvent:
        """Fail closed for malformed, stale, or otherwise rejected callbacks."""

        recovery = self._binder.recovery_status
        if (
            recovery is not None
            and recovery.lease.transaction_id is not None
            and (
                not transaction_id
                or transaction_id == recovery.lease.transaction_id
            )
        ):
            # A previous callback may already have latched recovery before its
            # WebView response was lost. Preserve that stronger state on retry
            # instead of re-exposing stale media controls through a generic error.
            return self._recovery_event(recovery.lease.transaction_id)

        active = self._binder.active_lease
        if (
            active is None
            or active.transaction_id is None
            or (transaction_id and transaction_id != active.transaction_id)
        ):
            return self._safe_error(transaction_id)

        active_transaction = active.transaction_id
        if active.provider_boundary_crossed:
            try:
                self._binder.provider_outcome_unknown(active_transaction)
            except Exception:
                # A concurrent/duplicate callback may already have moved the
                # lease into recovery. Never replace a stronger recovery state
                # with a generic browser failure.
                status = self._binder.recovery_status
                if (
                    status is not None
                    and status.lease.transaction_id == active_transaction
                ):
                    return self._recovery_event(active_transaction)
                return self._safe_error(active_transaction)
            return self._recovery_event(active_transaction)

        # Before provider dispatch there must never be a stranded global lease.
        # Retire the exact transaction. Session credential handoff has stronger
        # semantics in the canonical session owner: if a one-shot credential
        # already crossed into the browser, provider_not_started raises
        # MediaHostRecoveryRequired and the binder converts that into the shared
        # recovery latch instead of pretending the transaction was untouched.
        try:
            self._binder.provider_not_started(active_transaction)
        except MediaHostRecoveryRequired:
            return self._recovery_event(active_transaction)
        except Exception:
            status = self._binder.recovery_status
            if (
                status is not None
                and status.lease.transaction_id == active_transaction
            ):
                return self._recovery_event(active_transaction)
            return self._safe_error(active_transaction)

        focus = self._forget(active_transaction)
        return self._safe_error(focus_target=focus)

    # Mutation-port methods consumed by ClassroomMediaWebViewBridge.

    def set_local_source(
        self,
        source: MediaSource | str,
        enabled: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            lease = self._binder.prepare_local_source(source, enabled)
            return self._dispatch_event(lease, focus_target=focus_target)
        except Exception:
            return self._mutation_error(focus_target=focus_target)

    def set_publish_permission(
        self,
        participant_key: str,
        source: MediaSource | str,
        allowed: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            target_id = self._projection.resolve_participant_key(participant_key)
            lease = self._binder.prepare_publish_permission(
                actor_id=self._projection.controller.state.participant_id,
                target_id=target_id,
                source=source,
                allowed=allowed,
                operation_id=self._projection.new_operation_id(),
            )
            return self._dispatch_event(lease, focus_target=focus_target)
        except Exception:
            return self._mutation_error(focus_target=focus_target)

    def set_soft_mute(
        self,
        participant_key: str,
        muted: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            target_id = self._projection.resolve_participant_key(participant_key)
            lease = self._binder.prepare_soft_mute(
                actor_id=self._projection.controller.state.participant_id,
                target_id=target_id,
                muted=muted,
                operation_id=self._projection.new_operation_id(),
            )
            return self._dispatch_event(lease, focus_target=focus_target)
        except Exception:
            return self._mutation_error(focus_target=focus_target)

    def set_all_students_publish_permission(
        self,
        source: MediaSource | str,
        allowed: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            lease = self._binder.prepare_all_students_publish_permission(
                actor_id=self._projection.controller.state.participant_id,
                source=source,
                allowed=allowed,
                operation_id=self._projection.new_operation_id(),
            )
            return self._dispatch_event(lease, focus_target=focus_target)
        except Exception:
            return self._mutation_error(focus_target=focus_target)

    def set_all_students_soft_mute(
        self,
        muted: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            lease = self._binder.prepare_all_students_soft_mute(
                actor_id=self._projection.controller.state.participant_id,
                muted=muted,
                operation_id=self._projection.new_operation_id(),
            )
            return self._dispatch_event(lease, focus_target=focus_target)
        except Exception:
            return self._mutation_error(focus_target=focus_target)

    def remove_participant(
        self,
        participant_key: str,
        block: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            target_id = self._projection.resolve_participant_key(participant_key)
            lease = self._binder.prepare_remove_participant(
                actor_id=self._projection.controller.state.participant_id,
                target_id=target_id,
                block=block,
                operation_id=self._projection.new_operation_id(),
            )
            return self._dispatch_event(lease, focus_target=focus_target)
        except Exception:
            return self._mutation_error(focus_target=focus_target)

    def report_transport_lost(
        self,
        provider_snapshot: Mapping[str, object],
        *,
        focus_target: str = "classroom-media-heading",
    ) -> ClassroomMediaWebViewEvent:
        """Reconcile one provider-final disconnect without inventing policy."""

        _clean_disconnected_snapshot(provider_snapshot)

        recovery = self._binder.recovery_status
        if recovery is not None and recovery.lease.transaction_id is not None:
            return self._recovery_event(
                recovery.lease.transaction_id,
                focus_target=focus_target,
            )

        active = self._binder.active_lease
        if active is not None and active.transaction_id is not None:
            transaction_id = active.transaction_id
            try:
                if active.provider_boundary_crossed:
                    self._binder.provider_outcome_unknown(transaction_id)
                    return self._recovery_event(
                        transaction_id,
                        focus_target=focus_target,
                    )
                self._binder.provider_not_started(transaction_id)
            except MediaHostRecoveryRequired:
                return self._recovery_event(
                    transaction_id,
                    focus_target=focus_target,
                )
            except Exception:
                status = self._binder.recovery_status
                if (
                    status is not None
                    and status.lease.transaction_id == transaction_id
                ):
                    return self._recovery_event(
                        transaction_id,
                        focus_target=focus_target,
                    )
                return self._safe_error(
                    transaction_id,
                    focus_target=focus_target,
                )
            self._forget(transaction_id)

        try:
            self._projection.controller.mark_transport_lost()
        except Exception:
            # An already-retired/no-session notification is harmless but must
            # not manufacture a new room identity or provider state.
            state = self._projection.controller.state
            if state.room_id is None:
                return self._projection.updated_event(
                    focus_target=focus_target,
                )
            return self._safe_error(focus_target=focus_target)
        return self._projection.updated_event(focus_target=focus_target)

    def resolve_recovery_after_authoritative_reconciliation(
        self,
        transaction_id: str,
        *,
        focus_target: str = "classroom-media-heading",
    ) -> ClassroomMediaWebViewEvent:
        """Trusted-host completion after provider state was reconciled externally.

        This is deliberately not a browser callback.  The browser/provider cannot
        clear its own ambiguous outcome; a trusted host must first reconcile the
        authoritative provider state, then release the exact recovery transaction.
        """

        transaction = _transaction_id(transaction_id)
        status = self._binder.recovery_status
        if (
            status is None
            or status.lease.transaction_id != transaction
        ):
            raise MediaProviderExecutionError(
                "media provider recovery transaction is unknown"
            )
        self._binder.resolve_recovery(transaction)
        stored_focus = self._forget(transaction)
        return self._projection.updated_event(
            focus_target=stored_focus or focus_target,
        )

    # Trusted Python session entrypoints.  Browser payloads never accept a token.

    def prepare_join(
        self,
        credential: JoinCredential,
        *,
        now: datetime,
        focus_target: str = "classroom-media-heading",
    ) -> ClassroomMediaWebViewEvent:
        lease = self._binder.prepare_join(credential, now=now)
        return self._dispatch_event(lease, focus_target=focus_target)

    def prepare_reconnect(
        self,
        credential: JoinCredential,
        *,
        now: datetime,
        focus_target: str = "classroom-media-heading",
    ) -> ClassroomMediaWebViewEvent:
        lease = self._binder.prepare_reconnect(credential, now=now)
        return self._dispatch_event(lease, focus_target=focus_target)

    def prepare_disconnect(
        self,
        *,
        focus_target: str = "classroom-media-heading",
    ) -> ClassroomMediaWebViewEvent:
        lease = self._binder.prepare_disconnect()
        return self._dispatch_event(lease, focus_target=focus_target)

    # Narrow browser provider callbacks.

    def dispatch_provider(
        self,
        command: object,
        payload: Mapping[str, object] | None,
    ) -> ClassroomMediaWebViewEvent:
        transaction_id = ""
        try:
            command_id = _command(command)
            data = _payload(payload)

            if command_id == "media.provider_config":
                _exact(data, set())
                return ClassroomMediaWebViewEvent(
                    "provider-config",
                    {"config": self._provider_config.browser_payload()},
                )

            if command_id == "media.provider_transport_lost":
                _exact(data, {"snapshot"})
                return self.report_transport_lost(
                    _clean_disconnected_snapshot(data["snapshot"])
                )

            if command_id == "media.provider_take_credential":
                _exact(data, {"transaction_id"})
                transaction_id = _transaction_id(data["transaction_id"])
                credential = self._binder.take_session_credential(transaction_id)
                return ClassroomMediaWebViewEvent(
                    "provider-credential",
                    {
                        "transaction_id": transaction_id,
                        # Keep the binder's redacted mapping subclass intact in
                        # Python diagnostics. The WebView serializer still sees
                        # an ordinary mapping with the one-shot credential.
                        "credential": credential,
                    },
                )

            if command_id == "media.provider_dispatched":
                _exact(data, {"transaction_id"})
                transaction_id = _transaction_id(data["transaction_id"])
                self._binder.mark_provider_dispatched(transaction_id)
                return ClassroomMediaWebViewEvent(
                    "provider-ready",
                    {"transaction_id": transaction_id},
                )

            if command_id == "media.provider_not_started":
                _exact(data, {"transaction_id"})
                transaction_id = _transaction_id(data["transaction_id"])
                try:
                    self._binder.provider_not_started(transaction_id)
                except MediaHostRecoveryRequired:
                    return self._recovery_event(transaction_id)
                focus = self._forget(transaction_id)
                return self._safe_error(focus_target=focus)

            if command_id in {
                "media.provider_failed",
                "media.provider_outcome_unknown",
            }:
                _exact(data, {"transaction_id"})
                transaction_id = _transaction_id(data["transaction_id"])
                if command_id == "media.provider_failed":
                    self._binder.provider_failed(transaction_id)
                else:
                    self._binder.provider_outcome_unknown(transaction_id)
                return self._recovery_event(transaction_id)

            if command_id == "media.provider_connection_failed_clean":
                _exact(data, {"transaction_id", "snapshot"})
                transaction_id = _transaction_id(data["transaction_id"])
                snapshot = _snapshot(data["snapshot"])
                try:
                    self._binder.provider_connection_failed_clean(
                        transaction_id,
                        snapshot,
                    )
                except MediaHostRecoveryRequired:
                    return self._recovery_event(transaction_id)
                focus = self._forget(transaction_id)
                return self._safe_error(focus_target=focus)

            if command_id == "media.provider_session_success":
                _exact(data, {"transaction_id", "snapshot"})
                transaction_id = _transaction_id(data["transaction_id"])
                snapshot = _snapshot(data["snapshot"])
                try:
                    self._binder.acknowledge_session_success(
                        transaction_id,
                        snapshot,
                    )
                except MediaHostRecoveryRequired:
                    return self._recovery_event(transaction_id)
                focus = self._forget(transaction_id)
                return self._projection.updated_event(focus_target=focus)

            if command_id == "media.provider_effect_success":
                _exact(data, {"transaction_id", "chunk_index"})
                transaction_id = _transaction_id(data["transaction_id"])
                chunk_index = data["chunk_index"]
                if type(chunk_index) is not int or chunk_index < 0:
                    raise ValueError("media provider chunk index is invalid")
                try:
                    self._binder.acknowledge_effect_chunk_success(
                        transaction_id,
                        chunk_index,
                    )
                except MediaHostRecoveryRequired:
                    return self._recovery_event(transaction_id)
                if self._binder.active_lease is not None:
                    # The exact same transaction still owns the provider and has
                    # another bounded moderation chunk to execute.
                    provider = self._binder.pending_browser_payload(transaction_id)
                    return ClassroomMediaWebViewEvent(
                        "provider-dispatch",
                        {
                            "transaction_id": transaction_id,
                            "provider": dict(provider),
                            "provider_boundary_crossed": (
                                self._binder.active_lease.provider_boundary_crossed
                            ),
                            "focus_target": self._focus(transaction_id),
                        },
                    )
                focus = self._forget(transaction_id)
                return self._projection.updated_event(focus_target=focus)

            raise ValueError("unsupported media provider browser command")
        except Exception:
            # Never echo provider errors, tokens, URLs, identities or operation
            # payloads into the accessible surface. If the exact provider
            # boundary was already crossed, a malformed/failed callback makes
            # the provider outcome unknown and must enter recovery.
            return self._provider_callback_error(transaction_id)


def _command(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 96
        or value != value.strip()
        or re.fullmatch(r"media\.provider_[a-z_]+", value) is None
    ):
        raise ValueError("media provider browser command is invalid")
    return value


def _payload(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > _MAX_PROVIDER_PAYLOAD_FIELDS:
        raise ValueError("media provider browser payload is invalid")
    result: dict[str, object] = {}
    for key, item in value.items():
        if (
            type(key) is not str
            or not key
            or len(key) > 48
            or re.fullmatch(r"[a-z_]+", key) is None
        ):
            raise ValueError("media provider browser payload key is invalid")
        result[key] = item
    return result


def _exact(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise ValueError("media provider browser payload fields are invalid")


def _transaction_id(value: object) -> str:
    if type(value) is not str or _TRANSACTION_RE.fullmatch(value) is None:
        raise ValueError("media provider transaction identity is invalid")
    return value


def _snapshot(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("media provider snapshot is invalid")
    result = dict(value)
    expected = {
        "connected",
        "cleanup_required",
        "room_id",
        "participant_id",
        "microphone_enabled",
        "camera_enabled",
        "screen_share_enabled",
    }
    if set(result) != expected:
        raise ValueError("media provider snapshot fields are invalid")
    return result


def _clean_disconnected_snapshot(value: object) -> dict[str, object]:
    result = _snapshot(value)
    for key in (
        "connected",
        "cleanup_required",
        "microphone_enabled",
        "camera_enabled",
        "screen_share_enabled",
    ):
        if type(result[key]) is not bool:
            raise ValueError(
                "media provider transport-loss snapshot flags are invalid"
            )
    expected = {
        "connected": False,
        "cleanup_required": False,
        "room_id": None,
        "participant_id": None,
        "microphone_enabled": False,
        "camera_enabled": False,
        "screen_share_enabled": False,
    }
    if result != expected:
        raise ValueError(
            "media provider transport-loss snapshot is not cleanly disconnected"
        )
    return result


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _provider_url(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_PROVIDER_URL_CHARS
        or value != value.strip()
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError("LiveKit browser provider URL is invalid")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ValueError("LiveKit browser provider URL is invalid") from None
    if (
        parts.scheme not in {"wss", "ws"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
        or (port is None and ":" in parts.netloc.rsplit("]", 1)[-1])
        or (port is not None and port == 0)
    ):
        raise ValueError("LiveKit browser provider URL is invalid")
    if parts.scheme == "ws" and not _loopback_host(parts.hostname):
        raise ValueError("LiveKit browser provider URL must use WSS")
    return value[:-1] if value.endswith("/") else value


def _loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


__all__ = [
    "ClassroomMediaBrowserProviderConfig",
    "ClassroomMediaTransactionalWebView",
]
