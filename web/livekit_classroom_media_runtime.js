"use strict";

(function (global) {
  const MAX_DISPATCH_STEPS = 300;
  const TRANSACTION_RE = /^(?:host|session)-[0-9a-f]{32}$/;
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
    const token = String(value || "");
    if (!TRANSACTION_RE.test(token)) {
      throw new TypeError("media provider transaction identity is invalid");
    }
    return token;
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
    const operation = String(provider.operation || "");
    if (!OPERATIONS.has(operation)) {
      throw new TypeError("media provider operation is invalid");
    }

    if (operation === "set_local_source") {
      exactKeys(provider, ["transaction_id", "operation", "source", "enabled"], "local-source instruction");
      if (!["microphone", "camera", "screen_share"].includes(provider.source) ||
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
    } else if (operation === "recover_device") {
      exactKeys(
        provider,
        ["transaction_id", "operation", "kind", "device_id", "republish_enabled"],
        "device-recovery instruction"
      );
      if (!["microphone", "speaker", "camera"].includes(provider.kind) ||
          typeof provider.device_id !== "string" || !provider.device_id ||
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

  class ClassroomMediaProviderRuntime {
    constructor() {
      this._adapter = null;
      this._config = null;
      this._busy = false;
      this._transportLossSnapshot = null;
    }

    get configured() {
      return this._adapter !== null;
    }

    snapshot() {
      return this._adapter === null ? null : this._adapter.snapshot();
    }

    async _configure(invoke) {
      // Provider configuration belongs to the current trusted Python binding,
      // not to the lifetime of this WebView. Re-read it before every provider
      // transaction so a clean unbind/rebind cannot reuse a stale room URL or
      // moderation identity.
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

      const nextConfig = Object.freeze({
        server_url: config.server_url,
        moderation_participant_identity: config.moderation_participant_identity
      });
      if (this._adapter !== null && this._config !== null) {
        const unchanged =
          this._config.server_url === nextConfig.server_url &&
          this._config.moderation_participant_identity ===
            nextConfig.moderation_participant_identity;
        if (unchanged) return this._adapter;

        // A changed binding may replace the adapter only after the prior
        // provider session is proven quiescent. Never silently retarget a live
        // or cleanup-required LiveKit room.
        const previous = this._adapter.snapshot();
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
        if (previous.connected !== false ||
            previous.cleanup_required !== false ||
            previous.room_id !== null ||
            previous.participant_id !== null ||
            previous.microphone_enabled !== false ||
            previous.camera_enabled !== false ||
            previous.screen_share_enabled !== false) {
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
            this._transportLossSnapshot = snapshot;
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

    async _sessionFailure(invoke, transaction, adapter, operation) {
      if (operation === "connect" || operation === "reconnect") {
        let snapshot = null;
        try {
          snapshot = adapter.snapshot();
        } catch (_error) {
          snapshot = null;
        }
        if (snapshot && snapshot.connected === false && snapshot.cleanup_required === false) {
          try {
            return await invoke("media.provider_connection_failed_clean", {
              transaction_id: transaction,
              snapshot
            });
          } catch (_error) {
            return this._providerFailed(invoke, transaction);
          }
        }
      }
      return this._providerFailed(invoke, transaction);
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

    async _deliverTransportLoss(invoke) {
      const snapshot = this._transportLossSnapshot;
      if (snapshot === null) return null;
      let result;
      try {
        result = await invoke("media.provider_transport_lost", { snapshot });
      } catch (_error) {
        return null;
      }
      if (!result || typeof result !== "object") return null;
      if (this._transportLossSnapshot === snapshot) {
        this._transportLossSnapshot = null;
      }
      return result;
    }

    async reconcileTransport(invoke) {
      invoke = requireInvoke(invoke);
      if (this._busy || this._transportLossSnapshot === null) return null;
      this._busy = true;
      try {
        return await this._deliverTransportLoss(invoke);
      } finally {
        this._busy = false;
      }
    }

    async execute(event, invoke) {
      invoke = requireInvoke(invoke);
      if (this._busy) {
        try {
          const parsed = providerInstruction(event);
          return await this._providerNotStarted(invoke, parsed.transaction);
        } catch (_error) {
          return null;
        }
      }

      // A final provider disconnect can arrive between user actions. Retire the
      // newly prepared transaction before reconciling that older transport fact,
      // so stale canonical "connected" state cannot authorize a second provider
      // mutation.
      if (this._transportLossSnapshot !== null) {
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

      this._busy = true;
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
        this._busy = false;
      }
    }
  }

  // The runtime has mutable execution state (_busy, _adapter, _config).
  // Seal its shape without freezing those state slots.
  global.AccessibleChessClassroomMediaProviderRuntime = Object.seal(
    new ClassroomMediaProviderRuntime()
  );
})(window);
