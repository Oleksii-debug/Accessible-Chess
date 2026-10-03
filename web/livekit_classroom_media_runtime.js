"use strict";

(function (global) {
  const MAX_DISPATCH_STEPS = 300;
  const TRANSPORT_RETRY_MS = 2000;
  const MAX_PROVIDER_ID_LENGTH = 128;
  const MAX_DEVICE_ID_LENGTH = 512;
  const TRANSACTION_RE = /^(?:host|session)-[0-9a-f]{32}$/;
  const PROVIDER_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/;
  const SOURCE_NAMES = new Set(["microphone", "camera", "screen_share"]);
  const MODERATION_ACTIONS = new Set(["publish_permission", "soft_mute", "remove"]);
  const OPERATIONS = new Set([
    "connect",
    "reconnect",
    "disconnect",
    "set_local_source",
    "apply_moderation",
    "recover_device"
  ]);

  function exactKeys(value, expected, label) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new TypeError(label + " must be an object");
    }
    const keys = Object.keys(value).sort();
    const wanted = expected.slice().sort();
    if (keys.length !== wanted.length ||
        keys.some((key, index) => key !== wanted[index])) {
      throw new TypeError(label + " fields are invalid");
    }
    return value;
  }

  function transactionId(value) {
    if (typeof value !== "string" || !TRANSACTION_RE.test(value)) {
      throw new TypeError("media provider transaction identity is invalid");
    }
    return value;
  }

  function providerIdentifier(value, label) {
    if (typeof value !== "string" || !value ||
        value.length > MAX_PROVIDER_ID_LENGTH || !PROVIDER_ID_RE.test(value)) {
      throw new TypeError(label + " is invalid");
    }
    return value;
  }

  function validateModerationCommand(command) {
    exactKeys(
      command,
      ["operation_id", "actor_id", "target_id", "action", "source", "value"],
      "moderation command"
    );
    providerIdentifier(command.operation_id, "moderation operation id");
    providerIdentifier(command.actor_id, "moderation actor id");
    providerIdentifier(command.target_id, "moderation target id");
    if (typeof command.action !== "string" ||
        !MODERATION_ACTIONS.has(command.action)) {
      throw new TypeError("moderation action is invalid");
    }
    if (command.action === "publish_permission") {
      if (!SOURCE_NAMES.has(command.source) || typeof command.value !== "boolean") {
        throw new TypeError("publish permission command is invalid");
      }
    } else if (command.action === "soft_mute") {
      if (command.source !== "microphone" || typeof command.value !== "boolean") {
        throw new TypeError("soft mute command is invalid");
      }
    } else if (command.source !== null || typeof command.value !== "boolean") {
      throw new TypeError("remove command is invalid");
    }
    return command.operation_id;
  }

  function providerInstruction(event) {
    if (!event || event.kind !== "provider-dispatch") {
      throw new TypeError("media provider dispatch event is invalid");
    }
    const payload = event.payload && typeof event.payload === "object"
      ? event.payload
      : null;
    exactKeys(
      payload,
      ["transaction_id", "provider", "provider_boundary_crossed", "focus_target"],
      "media provider dispatch"
    );
    const transaction = transactionId(payload.transaction_id);
    if (typeof payload.provider_boundary_crossed !== "boolean") {
      throw new TypeError("media provider dispatch boundary flag is invalid");
    }
    const provider = payload.provider;
    if (!provider || typeof provider !== "object" || Array.isArray(provider)) {
      throw new TypeError("media provider instruction is invalid");
    }
    if (transactionId(provider.transaction_id) !== transaction) {
      throw new TypeError("media provider instruction transaction mismatch");
    }
    const operation = provider.operation;
    if (typeof operation !== "string" || !OPERATIONS.has(operation)) {
      throw new TypeError("media provider operation is invalid");
    }

    if (operation === "set_local_source") {
      exactKeys(provider, ["transaction_id", "operation", "source", "enabled"], "local-source instruction");
      if (!SOURCE_NAMES.has(provider.source) ||
          typeof provider.enabled !== "boolean") {
        throw new TypeError("local-source instruction is invalid");
      }
    } else if (operation === "apply_moderation") {
      exactKeys(
        provider,
        ["transaction_id", "operation", "chunk_index", "chunk_count", "commands"],
        "moderation instruction"
      );
      if (!Number.isInteger(provider.chunk_index) || provider.chunk_index < 0 ||
          !Number.isInteger(provider.chunk_count) || provider.chunk_count < 1 ||
          provider.chunk_index >= provider.chunk_count ||
          !Array.isArray(provider.commands) || provider.commands.length < 1 ||
          provider.commands.length > 24) {
        throw new TypeError("moderation instruction is invalid");
      }
      const operationIds = new Set();
      for (const command of provider.commands) {
        const operationId = validateModerationCommand(command);
        if (operationIds.has(operationId)) {
          throw new TypeError("moderation operation ids must be unique");
        }
        operationIds.add(operationId);
      }
    } else if (operation === "recover_device") {
      exactKeys(
        provider,
        ["transaction_id", "operation", "kind", "device_id", "republish_enabled"],
        "device-recovery instruction"
      );
      if (!["microphone", "speaker", "camera"].includes(provider.kind) ||
          typeof provider.device_id !== "string" || !provider.device_id ||
          provider.device_id.length > MAX_DEVICE_ID_LENGTH ||
          /[\u0000-\u001f\u007f]/.test(provider.device_id) ||
          typeof provider.republish_enabled !== "boolean") {
        throw new TypeError("device-recovery instruction is invalid");
      }
    } else {
      exactKeys(
        provider,
        ["transaction_id", "operation", "credential_required", "enabled_sources"],
        "session instruction"
      );
      if (typeof provider.credential_required !== "boolean" ||
          !Array.isArray(provider.enabled_sources)) {
        throw new TypeError("session instruction is invalid");
      }
      if ((operation === "connect" || operation === "reconnect") !== provider.credential_required) {
        throw new TypeError("session credential requirement is invalid");
      }
      const enabledSources = new Set();
      for (const source of provider.enabled_sources) {
        if (!["microphone", "camera", "screen_share"].includes(source) ||
            enabledSources.has(source)) {
          throw new TypeError("session enabled sources are invalid");
        }
        enabledSources.add(source);
      }
      if (operation === "connect" && provider.enabled_sources.length !== 0) {
        throw new TypeError("initial connect must not auto-publish media");
      }
      if (operation === "disconnect" && provider.enabled_sources.length !== 0) {
        throw new TypeError("disconnect instruction must not publish media");
      }
    }
    return {
      transaction,
      provider,
      providerBoundaryCrossed: payload.provider_boundary_crossed
    };
  }

  function requireInvoke(invoke) {
    if (typeof invoke !== "function") throw new TypeError("media provider invoke must be a function");
    return invoke;
  }

  function isCleanDisconnectedSnapshot(value) {
    try {
      exactKeys(
        value,
        [
          "connected",
          "cleanup_required",
          "room_id",
          "participant_id",
          "microphone_enabled",
          "camera_enabled",
          "screen_share_enabled"
        ],
        "media transport snapshot"
      );
    } catch (_error) {
      return false;
    }
    return value.connected === false &&
      value.cleanup_required === false &&
      value.room_id === null &&
      value.participant_id === null &&
      value.microphone_enabled === false &&
      value.camera_enabled === false &&
      value.screen_share_enabled === false;
  }

  class ClassroomMediaProviderRuntime {
    constructor() {
      this._adapter = null;
      this._config = null;
      this._busy = false;
      this._activeTransaction = null;
      this._cleanupRetryPending = false;
      this._transportLossSnapshot = null;
      this._transportRetryAt = 0;
    }

    get configured() {
      return this._adapter !== null;
    }

    snapshot() {
      return this._adapter === null ? null : this._adapter.snapshot();
    }

    _scheduleExistingAdapterCleanup() {
      if (this._adapter === null) return;
      try {
        const snapshot = this._adapter.snapshot();
        if (isCleanDisconnectedSnapshot(snapshot)) return;
        if (!this._rememberTransportLossSnapshot(snapshot)) {
          this._cleanupRetryPending = true;
          this._transportRetryAt = 0;
        }
      } catch (_error) {
        this._cleanupRetryPending = true;
        this._transportRetryAt = 0;
      }
    }

    async _configure(invoke) {
      // Provider configuration belongs to the current trusted Python binding,
      // not to the lifetime of this WebView. Re-read it before every provider
      // transaction so a clean unbind/rebind cannot reuse a stale room URL or
      // moderation identity.
      let nextConfig;
      try {
        const result = await invoke("media.provider_config", {});
        if (!result || result.kind !== "provider-config") {
          throw new Error("media provider config is unavailable");
        }
        const payload = result.payload && typeof result.payload === "object"
          ? result.payload
          : {};
        const config = payload.config;
        exactKeys(
          config,
          ["server_url", "moderation_participant_identity"],
          "media provider config"
        );
        if (typeof config.server_url !== "string" ||
            typeof config.moderation_participant_identity !== "string") {
          throw new TypeError("media provider config is invalid");
        }
        if (!global.LivekitClient || typeof global.LivekitClient.Room !== "function" ||
            !global.AccessibleChessLiveKitMedia ||
            typeof global.AccessibleChessLiveKitMedia.LiveKitClassroomMediaAdapter !== "function") {
          throw new Error("packaged LiveKit media runtime is unavailable");
        }

        nextConfig = Object.freeze({
          server_url: config.server_url,
          moderation_participant_identity: config.moderation_participant_identity
        });
      } catch (error) {
        this._scheduleExistingAdapterCleanup();
        throw error;
      }
      if (this._adapter !== null && this._config !== null) {
        const unchanged =
          this._config.server_url === nextConfig.server_url &&
          this._config.moderation_participant_identity ===
            nextConfig.moderation_participant_identity;
        if (unchanged) return this._adapter;

        // A changed binding may replace the adapter only after the prior
        // provider session is proven quiescent. Never silently retarget a live
        // or cleanup-required LiveKit room.
        let previous;
        try {
          previous = this._adapter.snapshot();
          exactKeys(
            previous,
            [
              "connected",
              "cleanup_required",
              "room_id",
              "participant_id",
              "microphone_enabled",
              "camera_enabled",
              "screen_share_enabled"
            ],
            "prior media provider snapshot"
          );
        } catch (_error) {
          // If the prior adapter cannot prove quiescence, do not retarget it
          // and do not forget it. Schedule teardown before any later provider
          // mutation can cross the boundary.
          this._cleanupRetryPending = true;
          this._transportRetryAt = 0;
          throw new Error(
            "media provider configuration changed while prior adapter state is unknown"
          );
        }
        if (previous.connected !== false ||
            previous.cleanup_required !== false ||
            previous.room_id !== null ||
            previous.participant_id !== null ||
            previous.microphone_enabled !== false ||
            previous.camera_enabled !== false ||
            previous.screen_share_enabled !== false) {
          this._rememberTransportLossSnapshot(previous);
          throw new Error(
            "media provider configuration changed while prior adapter is active"
          );
        }
      }

      const Adapter = global.AccessibleChessLiveKitMedia.LiveKitClassroomMediaAdapter;
      let adapter = null;
      adapter = new Adapter({
        livekit: global.LivekitClient,
        serverUrl: nextConfig.server_url,
        moderationParticipantIdentity: nextConfig.moderation_participant_identity,
        onTransportLost: (snapshot) => {
          if (this._adapter === adapter) {
            if (!this._rememberTransportLossSnapshot(snapshot)) {
              // A provider transport-loss signal with unusable state is still
              // evidence that the old Room must not authorize new media work.
              this._cleanupRetryPending = true;
              this._transportRetryAt = 0;
            }
          }
        }
      });
      this._adapter = adapter;
      this._config = nextConfig;
      return this._adapter;
    }

    async _providerNotStarted(invoke, transaction) {
      try {
        return await invoke("media.provider_not_started", { transaction_id: transaction });
      } catch (_error) {
        // The acknowledgement itself may have crossed the Python bridge before
        // its response was lost. Conservatively latch recovery rather than
        // strand a lease whose dispatch-marker state is now uncertain.
        return this._providerOutcomeUnknown(invoke, transaction);
      }
    }

    async _beforeProviderFailure(invoke, transaction, boundaryCrossed) {
      return boundaryCrossed
        ? this._providerOutcomeUnknown(invoke, transaction)
        : this._providerNotStarted(invoke, transaction);
    }

    async _providerOutcomeUnknown(invoke, transaction) {
      try {
        return await invoke("media.provider_outcome_unknown", {
          transaction_id: transaction
        });
      } catch (_error) {
        return null;
      }
    }

    async _providerFailed(invoke, transaction) {
      try {
        return await invoke("media.provider_failed", { transaction_id: transaction });
      } catch (_error) {
        return this._providerOutcomeUnknown(invoke, transaction);
      }
    }

    _rememberTransportLossSnapshot(snapshot) {
      if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
        return false;
      }
      this._transportLossSnapshot = snapshot;
      this._cleanupRetryPending =
        snapshot.connected === true || snapshot.cleanup_required === true;
      this._transportRetryAt = 0;
      return true;
    }

    async _settleCleanSessionFailure(invoke, transaction, operation, snapshot) {
      try {
        let result;
        if (operation === "disconnect") {
          result = await invoke("media.provider_session_success", {
            transaction_id: transaction,
            snapshot
          });
        } else {
          result = await invoke("media.provider_connection_failed_clean", {
            transaction_id: transaction,
            snapshot
          });
        }
        const payload = result && result.payload && typeof result.payload === "object"
          ? result.payload
          : {};
        const terminal = operation === "disconnect"
          ? Boolean(result && result.kind === "media-updated")
          : Boolean(
              result &&
              result.kind === "error" &&
              typeof payload.message === "string" &&
              payload.message.length > 0 &&
              payload.recovery_required !== true
            );
        if (!terminal) {
          // Provider teardown is already exact and clean, but canonical
          // acknowledgement is missing, malformed, or still requires trusted
          // reconciliation. Preserve that clean fact and fail closed through
          // the existing unknown-outcome authority unless Python already
          // returned its explicit recovery surface.
          this._rememberTransportLossSnapshot(snapshot);
          if (!(result && result.kind === "error" &&
                payload.recovery_required === true)) {
            const recovery = await this._providerOutcomeUnknown(
              invoke,
              transaction
            );
            return recovery || result;
          }
        }
        return result;
      } catch (_error) {
        const result = await this._providerFailed(invoke, transaction);
        // Browser/provider proof of clean teardown is not authority to release
        // an ambiguous Python recovery. Retain the snapshot so current #1201
        // can retry canonical transport-loss convergence after trusted recovery.
        this._rememberTransportLossSnapshot(snapshot);
        return result;
      }
    }

    async _sessionFailure(invoke, transaction, adapter, operation) {
      let snapshot = null;
      try {
        snapshot = adapter.snapshot();
      } catch (_error) {
        snapshot = null;
      }
      if (snapshot && isCleanDisconnectedSnapshot(snapshot)) {
        return this._settleCleanSessionFailure(
          invoke,
          transaction,
          operation,
          snapshot
        );
      }

      // Failed reconnect/source republish or disconnect can leave a validated
      // provider Room live while recovery hides media controls. Retry teardown
      // immediately so microphone/camera capture is not stranded behind the
      // recovery surface.
      try {
        snapshot = await adapter.disconnect();
      } catch (_error) {
        try {
          snapshot = adapter.snapshot();
        } catch (_snapshotError) {
          snapshot = null;
        }
      }
      if (snapshot && isCleanDisconnectedSnapshot(snapshot)) {
        return this._settleCleanSessionFailure(
          invoke,
          transaction,
          operation,
          snapshot
        );
      }

      const result = await this._providerFailed(invoke, transaction);
      // Keep retrying provider teardown from the existing transport reconciler.
      // Snapshot collection itself can fail while a provider Room remains live;
      // retain an independent cleanup latch so recovery never hides the only
      // path that can stop microphone/camera publication.
      this._cleanupRetryPending = true;
      this._transportRetryAt = 0;
      this._rememberTransportLossSnapshot(snapshot);
      return result;
    }

    async _takeCredential(invoke, transaction) {
      const result = await invoke("media.provider_take_credential", {
        transaction_id: transaction
      });
      if (!result || result.kind !== "provider-credential") {
        throw new Error("media provider credential handoff failed");
      }
      const payload = result.payload && typeof result.payload === "object"
        ? result.payload
        : {};
      if (transactionId(payload.transaction_id) !== transaction) {
        throw new Error("media provider credential transaction mismatch");
      }
      const credential = payload.credential;
      exactKeys(credential, ["room_id", "participant_id", "token"], "media provider credential");
      return credential;
    }

    async _markDispatched(invoke, transaction) {
      const result = await invoke("media.provider_dispatched", {
        transaction_id: transaction
      });
      if (!result || result.kind !== "provider-ready" ||
          !result.payload ||
          transactionId(result.payload.transaction_id) !== transaction) {
        throw new Error("media provider dispatch boundary was not accepted");
      }
    }

    async _executeOne(event, invoke) {
      const parsed = providerInstruction(event);
      const transaction = parsed.transaction;
      const provider = parsed.provider;
      let adapter;
      try {
        adapter = await this._configure(invoke);
      } catch (_error) {
        return this._beforeProviderFailure(
          invoke,
          transaction,
          parsed.providerBoundaryCrossed
        );
      }

      let credential = null;
      if (provider.credential_required === true) {
        try {
          credential = await this._takeCredential(invoke, transaction);
        } catch (_error) {
          return this._beforeProviderFailure(
            invoke,
            transaction,
            parsed.providerBoundaryCrossed
          );
        }
      }

      if (!parsed.providerBoundaryCrossed) {
        try {
          await this._markDispatched(invoke, transaction);
        } catch (_error) {
          return this._providerNotStarted(invoke, transaction);
        }
      }

      try {
        if (provider.operation === "connect") {
          await adapter.connect(credential, provider.enabled_sources);
        } else if (provider.operation === "reconnect") {
          await adapter.reconnect(credential, provider.enabled_sources);
        } else if (provider.operation === "disconnect") {
          await adapter.disconnect();
        } else if (provider.operation === "set_local_source") {
          await adapter.setLocalSource(provider.source, provider.enabled);
        } else if (provider.operation === "apply_moderation") {
          await adapter.applyModeration(provider.commands);
        } else if (provider.operation === "recover_device") {
          await adapter.recoverDevice(
            provider.kind,
            provider.device_id,
            provider.republish_enabled
          );
        } else {
          throw new Error("unsupported media provider operation");
        }
      } catch (_error) {
        if (provider.operation === "connect" ||
            provider.operation === "reconnect" ||
            provider.operation === "disconnect") {
          return this._sessionFailure(invoke, transaction, adapter, provider.operation);
        }
        return this._providerFailed(invoke, transaction);
      } finally {
        // Do not retain a one-shot secret after provider invocation.  The
        // adapter normalizes what it needs into provider-owned session state.
        credential = null;
      }

      try {
        if (provider.operation === "connect" ||
            provider.operation === "reconnect" ||
            provider.operation === "disconnect") {
          return await invoke("media.provider_session_success", {
            transaction_id: transaction,
            snapshot: adapter.snapshot()
          });
        }
        return await invoke("media.provider_effect_success", {
          transaction_id: transaction,
          chunk_index: provider.operation === "apply_moderation"
            ? provider.chunk_index
            : 0
        });
      } catch (_error) {
        // The provider mutation succeeded, but canonical acknowledgement did
        // not complete observably. Never leave the single global lease active
        // or pretend the provider did not run.
        return this._providerOutcomeUnknown(invoke, transaction);
      }
    }

    _deferTransportRetry() {
      this._transportRetryAt = Date.now() + TRANSPORT_RETRY_MS;
    }

    _transportReplyIsTerminal(result) {
      // A recovery latch is not canonical transport-loss completion.  Python may
      // still be holding an unrelated/active provider recovery while its media
      // controller remains connected.  Keep the clean disconnected provider
      // snapshot and retry after trusted recovery resolution; only an accepted
      // media-updated reply proves canonical transport loss was committed.
      return Boolean(
        result &&
        typeof result === "object" &&
        result.kind === "media-updated"
      );
    }

    async _deliverTransportLoss(invoke) {
      let snapshot = this._transportLossSnapshot;
      if (snapshot === null && !this._cleanupRetryPending) return null;

      // Provider-side room moves or failed session rollback can leave a
      // still-live Room that is no longer canonical. Retry teardown even when
      // provider snapshot collection itself previously failed.
      if (
        this._cleanupRetryPending ||
        (snapshot !== null &&
          (snapshot.connected === true || snapshot.cleanup_required === true))
      ) {
        if (this._adapter === null || typeof this._adapter.disconnect !== "function") {
          this._deferTransportRetry();
          return null;
        }
        try {
          snapshot = await this._adapter.disconnect();
          this._transportLossSnapshot = snapshot;
          this._cleanupRetryPending = !isCleanDisconnectedSnapshot(snapshot);
          this._transportRetryAt = 0;
        } catch (_error) {
          // A validated active Room can still publish media even though its
          // snapshot is not cleanup-only. Preserve the latest provider truth
          // and keep retrying teardown instead of hiding it behind recovery.
          try {
            snapshot = this._adapter.snapshot();
            this._transportLossSnapshot = snapshot;
            this._cleanupRetryPending = !isCleanDisconnectedSnapshot(snapshot);
          } catch (_snapshotError) {
            this._cleanupRetryPending = true;
          }
          this._deferTransportRetry();
          return null;
        }
      }
      if (!isCleanDisconnectedSnapshot(snapshot)) {
        this._cleanupRetryPending = true;
        this._deferTransportRetry();
        return null;
      }
      this._cleanupRetryPending = false;

      let result;
      try {
        result = await invoke("media.provider_transport_lost", { snapshot });
      } catch (_error) {
        this._deferTransportRetry();
        return null;
      }
      if (!this._transportReplyIsTerminal(result)) {
        this._deferTransportRetry();
        return result && typeof result === "object" ? result : null;
      }
      if (this._transportLossSnapshot === snapshot) {
        this._transportLossSnapshot = null;
        this._cleanupRetryPending = false;
        this._transportRetryAt = 0;
      }
      return result;
    }

    async reconcileTransport(invoke) {
      invoke = requireInvoke(invoke);
      if (
        this._busy ||
        (this._transportLossSnapshot === null && !this._cleanupRetryPending)
      ) return null;
      if (this._transportRetryAt > Date.now()) return null;
      this._busy = true;
      try {
        return await this._deliverTransportLoss(invoke);
      } finally {
        this._activeTransaction = null;
        this._busy = false;
      }
    }

    async execute(event, invoke) {
      invoke = requireInvoke(invoke);
      if (this._busy) {
        let transaction;
        try {
          transaction = providerInstruction(event).transaction;
        } catch (_error) {
          // A malformed provider payload can still belong to a valid prepared
          // Python transaction. Preserve that exact identity and retire it
          // instead of returning null while the global provider lease remains
          // stranded behind the operation that currently owns the runtime.
          try {
            transaction = transactionId(
              event && event.payload && event.payload.transaction_id
            );
          } catch (_identityError) {
            return null;
          }
        }
        if (transaction === this._activeTransaction) {
          // Duplicate delivery of the exact in-flight dispatch must not retire
          // the canonical transaction that currently owns the provider. The
          // original execution will publish the sole terminal acknowledgement.
          return { kind: "status", payload: {} };
        }
        return this._providerNotStarted(invoke, transaction);
      }

      // A final provider disconnect can arrive between user actions. Retire the
      // newly prepared transaction before reconciling that older transport fact,
      // so stale canonical "connected" state cannot authorize a second provider
      // mutation.
      if (this._transportLossSnapshot !== null || this._cleanupRetryPending) {
        let parsed;
        try {
          parsed = providerInstruction(event);
        } catch (_error) {
          return null;
        }
        if (parsed.providerBoundaryCrossed) {
          return this._providerOutcomeUnknown(invoke, parsed.transaction);
        }
        const retired = await this._providerNotStarted(invoke, parsed.transaction);
        if (retired && retired.payload && retired.payload.recovery_required === true) {
          return retired;
        }
        const reconciled = await this.reconcileTransport(invoke);
        return reconciled || retired;
      }

      let activeTransaction = null;
      try {
        activeTransaction = transactionId(
          event && event.payload && event.payload.transaction_id
        );
      } catch (_error) {
        activeTransaction = null;
      }
      this._busy = true;
      this._activeTransaction = activeTransaction;
      try {
        let current = event;
        for (let index = 0; index < MAX_DISPATCH_STEPS; index += 1) {
          if (!current || current.kind !== "provider-dispatch") return current;
          try {
            current = await this._executeOne(current, invoke);
          } catch (_error) {
            // The event still belongs to an exact Python transaction even when
            // its provider instruction is malformed. Ask the authoritative
            // binder to retire it as not-started. If Python already recorded a
            // crossed boundary, _providerNotStarted conservatively falls back
            // to provider_outcome_unknown instead of releasing the lease.
            let transaction;
            try {
              transaction = transactionId(
                current && current.payload && current.payload.transaction_id
              );
            } catch (_identityError) {
              return null;
            }
            current = await this._providerNotStarted(invoke, transaction);
          }
        }
        const parsed = providerInstruction(current);
        return this._providerFailed(invoke, parsed.transaction);
      } finally {
        this._activeTransaction = null;
        this._busy = false;
      }
    }
  }

  // The runtime has mutable execution state (_busy, _activeTransaction, _cleanupRetryPending, _adapter, _config).
  // Seal its shape without freezing those state slots.
  global.AccessibleChessClassroomMediaProviderRuntime = Object.seal(
    new ClassroomMediaProviderRuntime()
  );
})(window);
