"use strict";

(function (global) {
  const HOST_TRANSACTION_RE = /^host-[0-9a-f]{32}$/;
  const SESSION_TRANSACTION_RE = /^session-[0-9a-f]{32}$/;
  const SOURCES = new Set(["microphone", "camera", "screen_share"]);
  const DEVICE_KINDS = new Set(["microphone", "speaker", "camera"]);
  const MAX_MODERATION_CHUNK = 24;
  const SNAPSHOT_KEYS = Object.freeze([
    "camera_enabled",
    "cleanup_required",
    "connected",
    "microphone_enabled",
    "participant_id",
    "room_id",
    "screen_share_enabled"
  ]);

  class ClassroomMediaHostExecutorError extends Error {
    constructor(message) {
      super(message);
      this.name = "ClassroomMediaHostExecutorError";
    }
  }

  function exactKeys(value, expected, label) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new ClassroomMediaHostExecutorError(label + " must be an object");
    }
    const actual = Object.keys(value).sort();
    const wanted = expected.slice().sort();
    if (actual.length !== wanted.length ||
        !wanted.every((key, index) => actual[index] === key)) {
      throw new ClassroomMediaHostExecutorError(label + " fields are invalid");
    }
  }

  function transactionId(value, session) {
    if (typeof value !== "string" ||
        !(session ? SESSION_TRANSACTION_RE : HOST_TRANSACTION_RE).test(value)) {
      throw new ClassroomMediaHostExecutorError("media transaction id is invalid");
    }
    return value;
  }

  function source(value) {
    if (typeof value !== "string" || !SOURCES.has(value)) {
      throw new ClassroomMediaHostExecutorError("media source is invalid");
    }
    return value;
  }

  function uniqueSources(value) {
    if (!Array.isArray(value)) {
      throw new ClassroomMediaHostExecutorError("enabled sources are invalid");
    }
    const result = [];
    const seen = new Set();
    value.forEach((item) => {
      const normalized = source(item);
      if (seen.has(normalized)) {
        throw new ClassroomMediaHostExecutorError(
          "enabled sources contain duplicates"
        );
      }
      seen.add(normalized);
      result.push(normalized);
    });
    return result;
  }

  function normalizeSnapshot(value) {
    exactKeys(value, SNAPSHOT_KEYS, "provider snapshot");
    for (const key of [
      "connected",
      "cleanup_required",
      "microphone_enabled",
      "camera_enabled",
      "screen_share_enabled"
    ]) {
      if (typeof value[key] !== "boolean") {
        throw new ClassroomMediaHostExecutorError(
          "provider snapshot flags are invalid"
        );
      }
    }
    for (const key of ["room_id", "participant_id"]) {
      if (value[key] !== null && typeof value[key] !== "string") {
        throw new ClassroomMediaHostExecutorError(
          "provider snapshot identity is invalid"
        );
      }
    }
    return Object.freeze({
      connected: value.connected,
      cleanup_required: value.cleanup_required,
      room_id: value.room_id,
      participant_id: value.participant_id,
      microphone_enabled: value.microphone_enabled,
      camera_enabled: value.camera_enabled,
      screen_share_enabled: value.screen_share_enabled
    });
  }

  function safeSnapshot(adapter) {
    try {
      return normalizeSnapshot(adapter.snapshot());
    } catch (_error) {
      return null;
    }
  }

  function validateLocalSourceSuccessSnapshot(sourceValue, enabled, value) {
    const snapshot = normalizeSnapshot(value);
    const sourceKey = sourceValue === "microphone"
      ? "microphone_enabled"
      : sourceValue === "camera"
        ? "camera_enabled"
        : "screen_share_enabled";
    if (
      !snapshot.connected ||
      snapshot.cleanup_required ||
      snapshot.room_id === null ||
      snapshot.participant_id === null ||
      snapshot[sourceKey] !== enabled
    ) {
      throw new ClassroomMediaHostExecutorError(
        "media local-source provider snapshot does not match prepared effect"
      );
    }
    return snapshot;
  }

  function validateDeviceRecoverySuccessSnapshot(kind, republishEnabled, value) {
    const snapshot = normalizeSnapshot(value);
    if (
      !snapshot.connected ||
      snapshot.cleanup_required ||
      snapshot.room_id === null ||
      snapshot.participant_id === null
    ) {
      throw new ClassroomMediaHostExecutorError(
        "media device-recovery provider snapshot is not connected"
      );
    }
    if (
      kind === "microphone" &&
      snapshot.microphone_enabled !== republishEnabled
    ) {
      throw new ClassroomMediaHostExecutorError(
        "media microphone recovery snapshot does not match prepared effect"
      );
    }
    if (
      kind === "camera" &&
      snapshot.camera_enabled !== republishEnabled
    ) {
      throw new ClassroomMediaHostExecutorError(
        "media camera recovery snapshot does not match prepared effect"
      );
    }
    return snapshot;
  }

  function validateSessionSuccessSnapshot(operation, credentialValue, enabledSources, value) {
    const snapshot = normalizeSnapshot(value);
    if (operation === "disconnect") {
      const clean = !snapshot.connected &&
        !snapshot.cleanup_required &&
        snapshot.room_id === null &&
        snapshot.participant_id === null &&
        !snapshot.microphone_enabled &&
        !snapshot.camera_enabled &&
        !snapshot.screen_share_enabled;
      if (!clean) {
        throw new ClassroomMediaHostExecutorError(
          "media session disconnect snapshot is not clean"
        );
      }
      return snapshot;
    }

    const expectedSources = new Set(enabledSources);
    const matches = snapshot.connected &&
      !snapshot.cleanup_required &&
      snapshot.room_id === credentialValue.room_id &&
      snapshot.participant_id === credentialValue.participant_id &&
      snapshot.microphone_enabled === expectedSources.has("microphone") &&
      snapshot.camera_enabled === expectedSources.has("camera") &&
      snapshot.screen_share_enabled === expectedSources.has("screen_share");
    if (!matches) {
      throw new ClassroomMediaHostExecutorError(
        "media session provider snapshot does not match prepared effect"
      );
    }
    return snapshot;
  }

  function credential(value) {
    exactKeys(
      value,
      ["room_id", "participant_id", "token"],
      "media session credential"
    );
    if (typeof value.room_id !== "string" || !value.room_id ||
        typeof value.participant_id !== "string" || !value.participant_id ||
        typeof value.token !== "string" || !value.token) {
      throw new ClassroomMediaHostExecutorError(
        "media session credential is invalid"
      );
    }
    return {
      room_id: value.room_id,
      participant_id: value.participant_id,
      token: value.token
    };
  }

  function receipt(payload, status, snapshot) {
    return Object.freeze({
      transaction_id: payload.transaction_id,
      operation: payload.operation,
      status,
      chunk_index: payload.operation === "apply_moderation"
        ? payload.chunk_index
        : null,
      provider_snapshot: snapshot
    });
  }

  function validateNonSecretPayload(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new ClassroomMediaHostExecutorError(
        "media provider payload must be an object"
      );
    }
    const operation = payload.operation;
    if (operation === "set_local_source") {
      exactKeys(
        payload,
        ["transaction_id", "operation", "source", "enabled"],
        "local-source payload"
      );
      transactionId(payload.transaction_id, false);
      source(payload.source);
      if (typeof payload.enabled !== "boolean") {
        throw new ClassroomMediaHostExecutorError(
          "local-source enabled flag is invalid"
        );
      }
      return "host";
    }
    if (operation === "recover_device") {
      exactKeys(
        payload,
        [
          "transaction_id",
          "operation",
          "kind",
          "device_id",
          "republish_enabled"
        ],
        "device-recovery payload"
      );
      transactionId(payload.transaction_id, false);
      if (typeof payload.kind !== "string" || !DEVICE_KINDS.has(payload.kind)) {
        throw new ClassroomMediaHostExecutorError("media device kind is invalid");
      }
      if (typeof payload.device_id !== "string" || !payload.device_id) {
        throw new ClassroomMediaHostExecutorError("media device id is invalid");
      }
      if (typeof payload.republish_enabled !== "boolean") {
        throw new ClassroomMediaHostExecutorError(
          "device republish flag is invalid"
        );
      }
      return "host";
    }
    if (operation === "apply_moderation") {
      exactKeys(
        payload,
        [
          "transaction_id",
          "operation",
          "chunk_index",
          "chunk_count",
          "commands"
        ],
        "moderation payload"
      );
      transactionId(payload.transaction_id, false);
      if (!Number.isInteger(payload.chunk_index) || payload.chunk_index < 0 ||
          !Number.isInteger(payload.chunk_count) || payload.chunk_count < 1 ||
          payload.chunk_index >= payload.chunk_count) {
        throw new ClassroomMediaHostExecutorError(
          "moderation chunk position is invalid"
        );
      }
      if (!Array.isArray(payload.commands) ||
          payload.commands.length < 1 ||
          payload.commands.length > MAX_MODERATION_CHUNK) {
        throw new ClassroomMediaHostExecutorError(
          "moderation command chunk is invalid"
        );
      }
      return "host";
    }
    throw new ClassroomMediaHostExecutorError(
      "media provider operation is unsupported"
    );
  }

  function validateSessionPayload(payload) {
    exactKeys(
      payload,
      [
        "transaction_id",
        "operation",
        "credential_required",
        "enabled_sources"
      ],
      "media session payload"
    );
    transactionId(payload.transaction_id, true);
    const operation = payload.operation;
    if (!["connect", "reconnect", "disconnect"].includes(operation)) {
      throw new ClassroomMediaHostExecutorError(
        "media session operation is unsupported"
      );
    }
    if (typeof payload.credential_required !== "boolean") {
      throw new ClassroomMediaHostExecutorError(
        "media session credential flag is invalid"
      );
    }
    const enabled = uniqueSources(payload.enabled_sources);
    if (operation === "disconnect") {
      if (payload.credential_required || enabled.length) {
        throw new ClassroomMediaHostExecutorError(
          "disconnect session payload is invalid"
        );
      }
    } else {
      if (!payload.credential_required) {
        throw new ClassroomMediaHostExecutorError(
          "connect session credential is required"
        );
      }
      if (operation === "connect" && enabled.length) {
        throw new ClassroomMediaHostExecutorError(
          "initial join cannot auto-publish media"
        );
      }
    }
    return enabled;
  }

  class ClassroomMediaHostExecutor {
    constructor(options) {
      if (!options || typeof options !== "object") {
        throw new ClassroomMediaHostExecutorError(
          "media host executor options are required"
        );
      }
      const adapter = options.adapter;
      if (!adapter ||
          typeof adapter.connect !== "function" ||
          typeof adapter.reconnect !== "function" ||
          typeof adapter.disconnect !== "function" ||
          typeof adapter.setLocalSource !== "function" ||
          typeof adapter.applyModeration !== "function" ||
          typeof adapter.recoverDevice !== "function" ||
          typeof adapter.snapshot !== "function") {
        throw new ClassroomMediaHostExecutorError(
          "media provider adapter surface is unavailable"
        );
      }
      if (typeof options.takeCredential !== "function") {
        throw new ClassroomMediaHostExecutorError(
          "media credential handoff callback is required"
        );
      }
      Object.defineProperties(this, {
        _adapter: {
          value: adapter,
          enumerable: false,
          writable: false,
          configurable: false
        },
        _takeCredential: {
          value: options.takeCredential,
          enumerable: false,
          writable: false,
          configurable: false
        },
        _busy: {
          value: false,
          enumerable: false,
          writable: true,
          configurable: false
        }
      });
    }

    get busy() {
      return this._busy;
    }

    async execute(payload) {
      if (this._busy) {
        throw new ClassroomMediaHostExecutorError(
          "media provider executor already has an active transaction"
        );
      }

      const isSession = payload && typeof payload === "object" &&
        typeof payload.transaction_id === "string" &&
        SESSION_TRANSACTION_RE.test(payload.transaction_id);
      let enabledSources = null;
      if (isSession) {
        enabledSources = validateSessionPayload(payload);
      } else {
        validateNonSecretPayload(payload);
      }

      this._busy = true;
      try {
        if (isSession) {
          return await this._executeSession(payload, enabledSources);
        }
        return await this._executeNonSecret(payload);
      } finally {
        this._busy = false;
      }
    }

    async _executeSession(payload, enabledSources) {
      if (payload.operation === "disconnect") {
        try {
          const snapshot = validateSessionSuccessSnapshot(
            "disconnect",
            null,
            [],
            await this._adapter.disconnect()
          );
          return receipt(payload, "success", snapshot);
        } catch (_error) {
          return receipt(payload, "failed", safeSnapshot(this._adapter));
        }
      }

      let secret = null;
      try {
        secret = credential(
          await this._takeCredential(payload.transaction_id)
        );
      } catch (_error) {
        throw new ClassroomMediaHostExecutorError(
          "media session credential handoff failed"
        );
      }

      try {
        const method = payload.operation === "connect" ? "connect" : "reconnect";
        const snapshot = validateSessionSuccessSnapshot(
          payload.operation,
          secret,
          enabledSources,
          await this._adapter[method](secret, enabledSources)
        );
        return receipt(payload, "success", snapshot);
      } catch (_error) {
        return receipt(payload, "failed", safeSnapshot(this._adapter));
      } finally {
        secret = null;
      }
    }

    async _executeNonSecret(payload) {
      try {
        let snapshot;
        if (payload.operation === "set_local_source") {
          snapshot = validateLocalSourceSuccessSnapshot(
            payload.source,
            payload.enabled,
            await this._adapter.setLocalSource(
              payload.source,
              payload.enabled
            )
          );
        } else if (payload.operation === "recover_device") {
          snapshot = validateDeviceRecoverySuccessSnapshot(
            payload.kind,
            payload.republish_enabled,
            await this._adapter.recoverDevice(
              payload.kind,
              payload.device_id,
              payload.republish_enabled
            )
          );
        } else {
          await this._adapter.applyModeration(payload.commands);
          snapshot = this._adapter.snapshot();
        }
        return receipt(
          payload,
          "success",
          normalizeSnapshot(snapshot)
        );
      } catch (_error) {
        return receipt(payload, "failed", safeSnapshot(this._adapter));
      }
    }
  }

  const exported = Object.freeze({
    ClassroomMediaHostExecutor,
    ClassroomMediaHostExecutorError
  });
  global.AccessibleChessClassroomMediaHostExecutor = exported;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = exported;
  }
})(typeof window !== "undefined" ? window : globalThis);
