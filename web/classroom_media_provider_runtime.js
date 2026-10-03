"use strict";

(function (global) {
  const TRANSACTION_RE = /^(?:host|session)-[0-9a-f]{32}$/;
  const SESSION_OPERATIONS = new Set(["connect", "reconnect", "disconnect"]);

  class ClassroomMediaProviderRuntimeError extends Error {
    constructor(message) {
      super(message);
      this.name = "ClassroomMediaProviderRuntimeError";
    }
  }

  function exactKeys(value, expected, label) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new ClassroomMediaProviderRuntimeError(label + " must be an object");
    }
    const actual = Object.keys(value).sort();
    const wanted = expected.slice().sort();
    if (actual.length !== wanted.length ||
        !wanted.every((key, index) => actual[index] === key)) {
      throw new ClassroomMediaProviderRuntimeError(label + " fields are invalid");
    }
  }

  function transactionId(value) {
    if (typeof value !== "string" || !TRANSACTION_RE.test(value)) {
      throw new ClassroomMediaProviderRuntimeError(
        "media provider transaction id is invalid"
      );
    }
    return value;
  }

  function eventPayload(result, kind) {
    if (!result || typeof result !== "object" || result.kind !== kind ||
        !result.payload || typeof result.payload !== "object" ||
        Array.isArray(result.payload)) {
      throw new ClassroomMediaProviderRuntimeError(
        "media provider bridge returned an invalid " + kind + " event"
      );
    }
    return result.payload;
  }

  function dispatchEvent(result) {
    const payload = eventPayload(result, "provider-dispatch");
    exactKeys(
      payload,
      ["transaction_id", "provider", "focus_target"],
      "provider dispatch event"
    );
    const id = transactionId(payload.transaction_id);
    if (!payload.provider || typeof payload.provider !== "object" ||
        Array.isArray(payload.provider) ||
        payload.provider.transaction_id !== id) {
      throw new ClassroomMediaProviderRuntimeError(
        "provider dispatch payload is inconsistent"
      );
    }
    if (Object.prototype.hasOwnProperty.call(payload.provider, "token") ||
        Object.prototype.hasOwnProperty.call(payload.provider, "credential")) {
      throw new ClassroomMediaProviderRuntimeError(
        "provider dispatch payload exposed credential material"
      );
    }
    return {
      transactionId: id,
      provider: payload.provider
    };
  }

  function providerConfig(result) {
    const payload = eventPayload(result, "provider-config");
    exactKeys(payload, ["config"], "provider config event");
    const config = payload.config;
    exactKeys(
      config,
      ["server_url", "moderation_participant_identity"],
      "provider config"
    );
    if (typeof config.server_url !== "string" || !config.server_url ||
        typeof config.moderation_participant_identity !== "string" ||
        !config.moderation_participant_identity) {
      throw new ClassroomMediaProviderRuntimeError(
        "media provider config is invalid"
      );
    }
    return Object.freeze({
      serverUrl: config.server_url,
      moderationParticipantIdentity: config.moderation_participant_identity
    });
  }

  function credentialEvent(result, expectedTransactionId) {
    const payload = eventPayload(result, "provider-credential");
    exactKeys(
      payload,
      ["transaction_id", "credential"],
      "provider credential event"
    );
    if (transactionId(payload.transaction_id) !== expectedTransactionId) {
      throw new ClassroomMediaProviderRuntimeError(
        "provider credential transaction does not match"
      );
    }
    exactKeys(
      payload.credential,
      ["room_id", "participant_id", "token"],
      "provider credential"
    );
    for (const key of ["room_id", "participant_id", "token"]) {
      if (typeof payload.credential[key] !== "string" ||
          !payload.credential[key]) {
        throw new ClassroomMediaProviderRuntimeError(
          "provider credential is invalid"
        );
      }
    }
    return payload.credential;
  }

  function readyEvent(result, expectedTransactionId) {
    const payload = eventPayload(result, "provider-ready");
    exactKeys(payload, ["transaction_id"], "provider ready event");
    if (transactionId(payload.transaction_id) !== expectedTransactionId) {
      throw new ClassroomMediaProviderRuntimeError(
        "provider ready transaction does not match"
      );
    }
  }

  function receiptForTransaction(
    receipt,
    expectedTransactionId,
    expectedOperation,
    expectedChunkIndex
  ) {
    if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) {
      throw new ClassroomMediaProviderRuntimeError(
        "media provider executor receipt is invalid"
      );
    }
    exactKeys(
      receipt,
      [
        "transaction_id",
        "operation",
        "status",
        "chunk_index",
        "provider_snapshot"
      ],
      "provider executor receipt"
    );
    if (transactionId(receipt.transaction_id) !== expectedTransactionId) {
      throw new ClassroomMediaProviderRuntimeError(
        "provider executor receipt transaction does not match"
      );
    }
    if (receipt.operation !== expectedOperation) {
      throw new ClassroomMediaProviderRuntimeError(
        "provider executor receipt operation does not match dispatch"
      );
    }
    if (receipt.chunk_index !== expectedChunkIndex) {
      throw new ClassroomMediaProviderRuntimeError(
        "provider executor receipt chunk does not match dispatch"
      );
    }
    if (receipt.status !== "success" && receipt.status !== "failed") {
      throw new ClassroomMediaProviderRuntimeError(
        "provider executor receipt status is invalid"
      );
    }
    return receipt;
  }

  class ClassroomMediaProviderRuntime {
    constructor(options) {
      if (!options || typeof options !== "object" ||
          typeof options.invoke !== "function") {
        throw new ClassroomMediaProviderRuntimeError(
          "media provider runtime invoke callback is required"
        );
      }
      this._invoke = options.invoke;
      this._global = options.globalObject || global;
      this._executor = null;
      this._adapter = null;
      this._config = null;
      this._busy = false;
      this._credentialTransaction = null;
    }

    get busy() {
      return this._busy;
    }

    async _call(command, payload) {
      return await this._invoke(command, payload || {});
    }

    async _ensureExecutor(refreshConfig) {
      if (this._executor && !refreshConfig) return this._executor;

      const config = providerConfig(
        await this._call("media.provider_config", {})
      );
      if (this._executor) {
        const sameConfig = this._config &&
          this._config.serverUrl === config.serverUrl &&
          this._config.moderationParticipantIdentity ===
            config.moderationParticipantIdentity;
        if (sameConfig) return this._executor;

        let snapshot;
        try {
          snapshot = this._adapter && this._adapter.snapshot();
        } catch (_error) {
          throw new ClassroomMediaProviderRuntimeError(
            "existing media provider runtime cannot be safely reconfigured"
          );
        }
        if (!snapshot || typeof snapshot !== "object" ||
            snapshot.connected !== false ||
            snapshot.cleanup_required !== false) {
          throw new ClassroomMediaProviderRuntimeError(
            "active media provider runtime cannot change configuration"
          );
        }
        this._executor = null;
        this._adapter = null;
        this._config = null;
      }

      const livekit = this._global.LivekitClient;
      const mediaModule = this._global.AccessibleChessLiveKitMedia;
      const executorModule =
        this._global.AccessibleChessClassroomMediaHostExecutor;
      if (!livekit || typeof livekit.Room !== "function" ||
          !mediaModule ||
          typeof mediaModule.LiveKitClassroomMediaAdapter !== "function" ||
          !executorModule ||
          typeof executorModule.ClassroomMediaHostExecutor !== "function") {
        throw new ClassroomMediaProviderRuntimeError(
          "packaged classroom media provider runtime is unavailable"
        );
      }

      const adapter = new mediaModule.LiveKitClassroomMediaAdapter({
        livekit,
        serverUrl: config.serverUrl,
        moderationParticipantIdentity: config.moderationParticipantIdentity
      });
      const runtime = this;
      const executor = new executorModule.ClassroomMediaHostExecutor({
        adapter,
        takeCredential: async function (id) {
          const expected = transactionId(id);
          const credential = credentialEvent(
            await runtime._call(
              "media.provider_take_credential",
              { transaction_id: expected }
            ),
            expected
          );
          // The Python shipping binder marks the global provider-capability
          // boundary before returning this credential. A second explicit ready
          // acknowledgement proves the exact executor path reached the point
          // immediately before LiveKit invocation; it is idempotent for
          // connect/reconnect and remains fail-closed if the response is lost.
          runtime._credentialTransaction = expected;
          readyEvent(
            await runtime._call(
              "media.provider_dispatched",
              { transaction_id: expected }
            ),
            expected
          );
          return credential;
        }
      });

      this._adapter = adapter;
      this._executor = executor;
      this._config = config;
      return executor;
    }

    async _notStarted(transactionIdValue) {
      return await this._call(
        "media.provider_not_started",
        { transaction_id: transactionIdValue }
      );
    }

    async _executeOne(result, refreshConfig) {
      const dispatch = dispatchEvent(result);
      const id = dispatch.transactionId;
      let executor;
      try {
        executor = await this._ensureExecutor(refreshConfig === true);

        const operation = dispatch.provider.operation;
        const credentialSession =
          operation === "connect" || operation === "reconnect";
        if (!credentialSession) {
          readyEvent(
            await this._call(
              "media.provider_dispatched",
              { transaction_id: id }
            ),
            id
          );
        }

        const receipt = receiptForTransaction(
          await executor.execute(dispatch.provider),
          id,
          operation,
          operation === "apply_moderation"
            ? dispatch.provider.chunk_index
            : null
        );

        if (receipt.status === "success") {
          if (SESSION_OPERATIONS.has(operation)) {
            return await this._call(
              "media.provider_session_success",
              {
                transaction_id: id,
                snapshot: receipt.provider_snapshot
              }
            );
          }
          return await this._call(
            "media.provider_effect_success",
            {
              transaction_id: id,
              chunk_index: Number.isInteger(receipt.chunk_index)
                ? receipt.chunk_index
                : 0
            }
          );
        }

        if ((operation === "connect" || operation === "reconnect") &&
            receipt.provider_snapshot !== null) {
          return await this._call(
            "media.provider_connection_failed_clean",
            {
              transaction_id: id,
              snapshot: receipt.provider_snapshot
            }
          );
        }
        return await this._call(
          "media.provider_failed",
          { transaction_id: id }
        );
      } catch (_error) {
        // The Python owner decides whether this is still a true pre-provider
        // cancellation or whether a credential/dispatch boundary had already
        // crossed and must become recovery. This single callback is therefore
        // safe across setup failures, credential handoff failures and lost
        // provider-ready responses.
        return await this._notStarted(id);
      } finally {
        if (this._credentialTransaction === id) {
          this._credentialTransaction = null;
        }
      }
    }

    async settle(initialEvent) {
      if (this._busy) {
        throw new ClassroomMediaProviderRuntimeError(
          "media provider runtime already has an active transaction"
        );
      }
      this._busy = true;
      try {
        let current = initialEvent;
        let steps = 0;
        while (current && current.kind === "provider-dispatch") {
          steps += 1;
          if (steps > 512) {
            throw new ClassroomMediaProviderRuntimeError(
              "media provider transaction exceeded the bounded dispatch count"
            );
          }
          current = await this._executeOne(current, steps === 1);
        }
        if (!current || typeof current !== "object") {
          throw new ClassroomMediaProviderRuntimeError(
            "media provider bridge returned no terminal event"
          );
        }
        return current;
      } finally {
        this._busy = false;
      }
    }
  }

  const exported = Object.freeze({
    ClassroomMediaProviderRuntime,
    ClassroomMediaProviderRuntimeError
  });
  global.AccessibleChessClassroomMediaProviderRuntime = exported;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = exported;
  }
})(typeof window !== "undefined" ? window : globalThis);
