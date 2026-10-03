"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "livekit_classroom_media_runtime.js"),
  "utf8"
);

function loadRuntime(Adapter) {
  const sandbox = {
    Promise,
    URL,
    setTimeout,
    clearTimeout,
    LivekitClient: { Room: function Room() {} },
    AccessibleChessLiveKitMedia: {
      LiveKitClassroomMediaAdapter: Adapter
    }
  };
  sandbox.window = sandbox;
  vm.runInNewContext(SOURCE, sandbox, {
    filename: "livekit_classroom_media_runtime.js"
  });
  return sandbox.AccessibleChessClassroomMediaProviderRuntime;
}

function dispatch(transactionId, provider, crossed) {
  return {
    kind: "provider-dispatch",
    payload: {
      transaction_id: transactionId,
      provider,
      provider_boundary_crossed: crossed,
      focus_target: "classroom-media-heading"
    }
  };
}

function configResult(
  serverUrl = "wss://media.example.test",
  moderationParticipantIdentity = "moderation-service"
) {
  return {
    kind: "provider-config",
    payload: {
      config: {
        server_url: serverUrl,
        moderation_participant_identity: moderationParticipantIdentity
      }
    }
  };
}

function isCleanSnapshot(value) {
  return value &&
    value.connected === false &&
    value.cleanup_required === false &&
    value.room_id === null &&
    value.participant_id === null &&
    value.microphone_enabled === false &&
    value.camera_enabled === false &&
    value.screen_share_enabled === false;
}

class RecordingAdapter {
  constructor(options) {
    this.options = options;
    this.calls = [];
    this._snapshot = {
      connected: false,
      cleanup_required: false,
      room_id: null,
      participant_id: null,
      microphone_enabled: false,
      camera_enabled: false,
      screen_share_enabled: false
    };
    RecordingAdapter.instances.push(this);
  }

  async connect(credential, enabledSources) {
    this.calls.push(["connect", credential, enabledSources]);
    this._snapshot = {
      connected: true,
      cleanup_required: false,
      room_id: credential.room_id,
      participant_id: credential.participant_id,
      microphone_enabled: false,
      camera_enabled: false,
      screen_share_enabled: false
    };
    return this.snapshot();
  }

  async reconnect(credential, enabledSources) {
    this.calls.push(["reconnect", credential, enabledSources]);
    return this.connect(credential, enabledSources);
  }

  async disconnect() {
    this.calls.push(["disconnect"]);
    if (this.failDisconnectOnce === true) {
      this.failDisconnectOnce = false;
      throw new Error("provider cleanup failed");
    }
    this._snapshot = {
      connected: false,
      cleanup_required: false,
      room_id: null,
      participant_id: null,
      microphone_enabled: false,
      camera_enabled: false,
      screen_share_enabled: false
    };
    return this.snapshot();
  }

  async setLocalSource(source, enabled) {
    this.calls.push(["setLocalSource", source, enabled]);
    return this.snapshot();
  }

  async applyModeration(commands) {
    this.calls.push(["applyModeration", commands]);
  }

  async recoverDevice(kind, deviceId, republishEnabled) {
    this.calls.push(["recoverDevice", kind, deviceId, republishEnabled]);
    return this.snapshot();
  }

  loseTransport() {
    this._snapshot = {
      connected: false,
      cleanup_required: false,
      room_id: null,
      participant_id: null,
      microphone_enabled: false,
      camera_enabled: false,
      screen_share_enabled: false
    };
    if (typeof this.options.onTransportLost === "function") {
      this.options.onTransportLost(this.snapshot());
    }
  }

  moveTransport() {
    this._snapshot = {
      connected: false,
      cleanup_required: true,
      room_id: null,
      participant_id: null,
      microphone_enabled: false,
      camera_enabled: false,
      screen_share_enabled: false
    };
    if (typeof this.options.onTransportLost === "function") {
      this.options.onTransportLost(this.snapshot());
    }
  }

  snapshot() {
    return Object.assign({}, this._snapshot);
  }
}
RecordingAdapter.instances = [];

async function testMultiChunkMarksProviderBoundaryOnce() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const transaction = "host-" + "1".repeat(32);
  const first = dispatch(transaction, {
    transaction_id: transaction,
    operation: "apply_moderation",
    chunk_index: 0,
    chunk_count: 2,
    commands: [{
      operation_id: "op-1",
      actor_id: "teacher-1",
      target_id: "student-1",
      action: "soft_mute",
      source: "microphone",
      value: true
    }]
  }, false);
  const second = dispatch(transaction, {
    transaction_id: transaction,
    operation: "apply_moderation",
    chunk_index: 1,
    chunk_count: 2,
    commands: [{
      operation_id: "op-2",
      actor_id: "teacher-1",
      target_id: "student-2",
      action: "soft_mute",
      source: "microphone",
      value: true
    }]
  }, true);

  const bridgeCalls = [];
  async function invoke(command, payload) {
    bridgeCalls.push([command, payload]);
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: transaction } };
    }
    if (command === "media.provider_effect_success" && payload.chunk_index === 0) {
      return second;
    }
    if (command === "media.provider_effect_success" && payload.chunk_index === 1) {
      return {
        kind: "media-updated",
        payload: { snapshot: {}, focus_target: "classroom-media-heading" }
      };
    }
    throw new Error("unexpected bridge command " + command);
  }

  const result = await runtime.execute(first, invoke);
  assert.equal(result.kind, "media-updated");
  assert.equal(
    bridgeCalls.filter((item) => item[0] === "media.provider_dispatched").length,
    1
  );
  assert.deepEqual(
    RecordingAdapter.instances[0].calls.map((item) => item[0]),
    ["applyModeration", "applyModeration"]
  );
  assert.deepEqual(
    bridgeCalls
      .filter((item) => item[0] === "media.provider_effect_success")
      .map((item) => item[1].chunk_index),
    [0, 1]
  );
}

async function testJoinTakesCredentialBeforeDispatchAndReturnsExactSnapshot() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const transaction = "session-" + "2".repeat(32);
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false);
  const order = [];

  async function invoke(command, payload) {
    order.push(command);
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: transaction,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "one-shot-secret"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: transaction } };
    }
    if (command === "media.provider_session_success") {
      assert.deepEqual(payload.snapshot, {
        connected: true,
        cleanup_required: false,
        room_id: "room-1",
        participant_id: "student-1",
        microphone_enabled: false,
        camera_enabled: false,
        screen_share_enabled: false
      });
      return {
        kind: "media-updated",
        payload: { snapshot: { connected: true } }
      };
    }
    throw new Error("unexpected bridge command " + command);
  }

  const result = await runtime.execute(event, invoke);
  assert.equal(result.kind, "media-updated");
  assert.deepEqual(order, [
    "media.provider_config",
    "media.provider_take_credential",
    "media.provider_dispatched",
    "media.provider_session_success"
  ]);
  assert.equal(RecordingAdapter.instances[0].calls[0][0], "connect");
  assert.equal(RecordingAdapter.instances[0].calls[0][1].token, "one-shot-secret");
  assert.equal(JSON.stringify(result).includes("one-shot-secret"), false);
}

async function testMissingRuntimeConfigurationRetiresBeforeDispatch() {
  class NeverAdapter extends RecordingAdapter {
    constructor(options) {
      super(options);
      throw new Error("adapter must not be constructed");
    }
  }
  const runtime = loadRuntime(NeverAdapter);
  const transaction = "host-" + "3".repeat(32);
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "set_local_source",
    source: "camera",
    enabled: true
  }, false);
  const calls = [];

  const result = await runtime.execute(event, async (command) => {
    calls.push(command);
    if (command === "media.provider_config") {
      return { kind: "error", payload: {} };
    }
    if (command === "media.provider_not_started") {
      return { kind: "error", payload: { message: "sanitized" } };
    }
    throw new Error("unexpected command");
  });

  assert.equal(result.kind, "error");
  assert.deepEqual(calls, [
    "media.provider_config",
    "media.provider_not_started"
  ]);
  assert.equal(calls.includes("media.provider_dispatched"), false);
}

async function testCleanConnectFailureUsesExactCleanFailureCallback() {
  class CleanFailAdapter extends RecordingAdapter {
    async connect() {
      this.calls.push(["connect-failed-clean"]);
      throw new Error("provider detail");
    }
  }
  const runtime = loadRuntime(CleanFailAdapter);
  const transaction = "session-" + "4".repeat(32);
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false);
  const calls = [];

  const result = await runtime.execute(event, async (command, payload) => {
    calls.push(command);
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: transaction,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "one-shot-secret"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: transaction } };
    }
    if (command === "media.provider_connection_failed_clean") {
      assert.equal(payload.snapshot.connected, false);
      assert.equal(payload.snapshot.cleanup_required, false);
      return { kind: "error", payload: { message: "sanitized" } };
    }
    throw new Error("unexpected command " + command);
  });

  assert.equal(result.kind, "error");
  assert.equal(calls.includes("media.provider_failed"), false);
  assert.equal(calls.includes("media.provider_connection_failed_clean"), true);
}

async function testMalformedCleanConnectAckFailsClosedAndRetainsSnapshot() {
  class CleanFailAdapter extends RecordingAdapter {
    async connect() {
      this.calls.push(["connect-failed-clean-malformed-ack"]);
      throw new Error("provider detail");
    }
  }
  const runtime = loadRuntime(CleanFailAdapter);
  const transaction = "session-" + "5".repeat(32);
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false);
  const calls = [];
  let transportCalls = 0;

  const invoke = async (command, payload) => {
    calls.push(command);
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: transaction,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "one-shot-secret"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: transaction } };
    }
    if (command === "media.provider_connection_failed_clean") {
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      return { kind: "error", payload: {} };
    }
    if (command === "media.provider_outcome_unknown") {
      assert.equal(payload.transaction_id, transaction);
      return {
        kind: "error",
        payload: { message: "sanitized", recovery_required: true }
      };
    }
    if (command === "media.provider_transport_lost") {
      transportCalls += 1;
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      return { kind: "media-updated", payload: {} };
    }
    throw new Error("unexpected command " + command);
  };

  const result = await runtime.execute(event, invoke);
  assert.equal(result.kind, "error");
  assert.equal(result.payload.recovery_required, true);
  assert.equal(calls.includes("media.provider_outcome_unknown"), true);
  assert.equal(isCleanSnapshot(runtime._transportLossSnapshot), true);

  runtime._transportRetryAt = 0;
  const converged = await runtime.reconcileTransport(invoke);
  assert.equal(converged.kind, "media-updated");
  assert.equal(transportCalls, 1);
  assert.equal(runtime._transportLossSnapshot, null);
}

async function testProviderEffectFailureRequiresRecoveryCallback() {
  class EffectFailAdapter extends RecordingAdapter {
    async setLocalSource() {
      this.calls.push(["setLocalSource-failed"]);
      throw new Error("provider detail");
    }
  }
  const runtime = loadRuntime(EffectFailAdapter);
  const transaction = "host-" + "5".repeat(32);
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "set_local_source",
    source: "microphone",
    enabled: true
  }, false);
  const calls = [];

  const result = await runtime.execute(event, async (command) => {
    calls.push(command);
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: transaction } };
    }
    if (command === "media.provider_failed") {
      return {
        kind: "error",
        payload: { message: "sanitized", recovery_required: true }
      };
    }
    throw new Error("unexpected command " + command);
  });

  assert.equal(result.payload.recovery_required, true);
  assert.deepEqual(calls, [
    "media.provider_config",
    "media.provider_dispatched",
    "media.provider_failed"
  ]);
}

async function testProviderSuccessAckLossRequiresRecovery() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const transaction = "host-" + "8".repeat(32);
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "set_local_source",
    source: "microphone",
    enabled: true
  }, false);
  const calls = [];

  const result = await runtime.execute(event, async (command, payload) => {
    calls.push(command);
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_dispatched") {
      return {
        kind: "provider-ready",
        payload: { transaction_id: payload.transaction_id }
      };
    }
    if (command === "media.provider_effect_success") {
      throw new Error("bridge response lost after provider success");
    }
    if (command === "media.provider_outcome_unknown") {
      return {
        kind: "error",
        payload: {
          message: "sanitized",
          recovery_required: true,
          transaction_id: payload.transaction_id
        }
      };
    }
    throw new Error("unexpected command " + command);
  });

  assert.equal(result.kind, "error");
  assert.equal(result.payload.recovery_required, true);
  assert.deepEqual(calls, [
    "media.provider_config",
    "media.provider_dispatched",
    "media.provider_effect_success",
    "media.provider_outcome_unknown"
  ]);
  assert.deepEqual(
    RecordingAdapter.instances[0].calls.map((item) => item[0]),
    ["setLocalSource"]
  );
}

async function testCrossedTransactionConfigurationLossRequiresRecovery() {
  class NeverConstructedAdapter extends RecordingAdapter {
    constructor(options) {
      super(options);
      throw new Error("adapter must not be reconstructed");
    }
  }
  const runtime = loadRuntime(NeverConstructedAdapter);
  const transaction = "host-" + "9".repeat(32);
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "apply_moderation",
    chunk_index: 1,
    chunk_count: 2,
    commands: [{
      operation_id: "op-second",
      actor_id: "teacher-1",
      target_id: "student-2",
      action: "soft_mute",
      source: "microphone",
      value: true
    }]
  }, true);
  const calls = [];

  const result = await runtime.execute(event, async (command, payload) => {
    calls.push(command);
    if (command === "media.provider_config") {
      return { kind: "error", payload: { message: "unavailable" } };
    }
    if (command === "media.provider_outcome_unknown") {
      return {
        kind: "error",
        payload: {
          message: "sanitized",
          recovery_required: true,
          transaction_id: payload.transaction_id
        }
      };
    }
    if (command === "media.provider_not_started") {
      throw new Error("crossed transaction must not be retired as not started");
    }
    throw new Error("unexpected command " + command);
  });

  assert.equal(result.kind, "error");
  assert.equal(result.payload.recovery_required, true);
  assert.deepEqual(calls, [
    "media.provider_config",
    "media.provider_outcome_unknown"
  ]);
}

async function testMalformedSessionInstructionRetiresBeforeCredentialHandoff() {
  const cases = [
    {
      label: "initial connect auto-publish",
      operation: "connect",
      enabled_sources: ["camera"]
    },
    {
      label: "reconnect duplicate source",
      operation: "reconnect",
      enabled_sources: ["camera", "camera"]
    },
    {
      label: "reconnect unknown source",
      operation: "reconnect",
      enabled_sources: ["unknown-source"]
    }
  ];

  for (let index = 0; index < cases.length; index += 1) {
    RecordingAdapter.instances.length = 0;
    const runtime = loadRuntime(RecordingAdapter);
    const transaction = "session-" + String(index + 1).repeat(32);
    const bridgeCalls = [];
    const event = dispatch(transaction, {
      transaction_id: transaction,
      operation: cases[index].operation,
      credential_required: true,
      enabled_sources: cases[index].enabled_sources
    }, false);

    const result = await runtime.execute(event, async (command, payload) => {
      bridgeCalls.push([command, payload.transaction_id || null]);
      if (command === "media.provider_not_started") {
        return { kind: "error", payload: { message: "sanitized" } };
      }
      throw new Error("malformed session instruction crossed unexpected bridge command");
    });

    assert.equal(result.kind, "error", cases[index].label);
    assert.deepEqual(
      bridgeCalls,
      [["media.provider_not_started", transaction]],
      cases[index].label
    );
    assert.equal(RecordingAdapter.instances.length, 0, cases[index].label);
  }
}

async function testCoercedProviderFieldsRetireBeforeProviderBoundary() {
  const transaction = "host-" + "c".repeat(32);
  const cases = [
    {
      label: "transaction object coercion",
      provider: {
        transaction_id: { toString: () => transaction },
        operation: "set_local_source",
        source: "camera",
        enabled: true
      }
    },
    {
      label: "operation object coercion",
      provider: {
        transaction_id: transaction,
        operation: { toString: () => "set_local_source" },
        source: "camera",
        enabled: true
      }
    }
  ];

  for (const item of cases) {
    RecordingAdapter.instances.length = 0;
    const runtime = loadRuntime(RecordingAdapter);
    const bridgeCalls = [];
    const event = dispatch(transaction, item.provider, false);
    const result = await runtime.execute(event, async (command, payload) => {
      bridgeCalls.push([command, payload.transaction_id]);
      if (command === "media.provider_not_started") {
        return { kind: "error", payload: { message: "sanitized" } };
      }
      throw new Error("coerced provider field crossed unexpected bridge command");
    });

    assert.equal(result.kind, "error", item.label);
    assert.deepEqual(
      bridgeCalls,
      [["media.provider_not_started", transaction]],
      item.label
    );
    assert.equal(RecordingAdapter.instances.length, 0, item.label);
  }
}

async function testMalformedCrossedInstructionEscalatesToUnknownRecovery() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const transaction = "host-" + "e".repeat(32);
  const bridgeCalls = [];
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "set_local_source",
    source: "not-a-source",
    enabled: true
  }, true);

  const result = await runtime.execute(event, async (command, payload) => {
    bridgeCalls.push(command);
    assert.equal(payload.transaction_id, transaction);
    if (command === "media.provider_not_started") {
      throw new Error("authoritative binder says provider boundary already crossed");
    }
    if (command === "media.provider_outcome_unknown") {
      return {
        kind: "error",
        payload: {
          recovery_required: true,
          transaction_id: transaction
        }
      };
    }
    throw new Error("unexpected command " + command);
  });

  assert.equal(result.kind, "error");
  assert.equal(result.payload.recovery_required, true);
  assert.deepEqual(bridgeCalls, [
    "media.provider_not_started",
    "media.provider_outcome_unknown"
  ]);
  assert.equal(RecordingAdapter.instances.length, 0);
}

async function testMalformedModerationRetiresBeforeProviderBoundary() {
  const baseCommand = {
    operation_id: "operation-1",
    actor_id: "teacher-1",
    target_id: "student-1",
    action: "soft_mute",
    source: "microphone",
    value: true
  };
  const cases = [
    {
      label: "extra command field",
      commands: [Object.assign({}, baseCommand, { unexpected: true })]
    },
    {
      label: "invalid actor identity",
      commands: [Object.assign({}, baseCommand, { actor_id: "teacher 1" })]
    },
    {
      label: "invalid soft mute source",
      commands: [Object.assign({}, baseCommand, { source: "camera" })]
    },
    {
      label: "duplicate operation identities",
      commands: [
        baseCommand,
        Object.assign({}, baseCommand, { target_id: "student-2" })
      ]
    }
  ];

  for (let index = 0; index < cases.length; index += 1) {
    RecordingAdapter.instances.length = 0;
    const runtime = loadRuntime(RecordingAdapter);
    const transaction = "host-" + String(index + 3).repeat(32);
    const calls = [];
    const event = dispatch(transaction, {
      transaction_id: transaction,
      operation: "apply_moderation",
      chunk_index: 0,
      chunk_count: 1,
      commands: cases[index].commands
    }, false);

    const result = await runtime.execute(event, async (command, payload) => {
      calls.push([command, payload.transaction_id || null]);
      if (command === "media.provider_not_started") {
        return { kind: "error", payload: { message: "sanitized" } };
      }
      throw new Error("malformed moderation crossed unexpected bridge command");
    });

    assert.equal(result.kind, "error", cases[index].label);
    assert.deepEqual(
      calls,
      [["media.provider_not_started", transaction]],
      cases[index].label
    );
    assert.equal(RecordingAdapter.instances.length, 0, cases[index].label);
  }
}

async function testMalformedDeviceRecoveryRetiresBeforeProviderBoundary() {
  const cases = [
    { label: "oversized device id", deviceId: "x".repeat(513) },
    { label: "control character device id", deviceId: "camera\u0000device" }
  ];

  for (let index = 0; index < cases.length; index += 1) {
    RecordingAdapter.instances.length = 0;
    const runtime = loadRuntime(RecordingAdapter);
    const transaction = "host-" + String(index + 7).repeat(32);
    const calls = [];
    const event = dispatch(transaction, {
      transaction_id: transaction,
      operation: "recover_device",
      kind: "camera",
      device_id: cases[index].deviceId,
      republish_enabled: false
    }, false);

    const result = await runtime.execute(event, async (command, payload) => {
      calls.push([command, payload.transaction_id || null]);
      if (command === "media.provider_not_started") {
        return { kind: "error", payload: { message: "sanitized" } };
      }
      throw new Error("malformed device recovery crossed unexpected bridge command");
    });

    assert.equal(result.kind, "error", cases[index].label);
    assert.deepEqual(
      calls,
      [["media.provider_not_started", transaction]],
      cases[index].label
    );
    assert.equal(RecordingAdapter.instances.length, 0, cases[index].label);
  }
}

async function testDuplicateInflightDispatchDoesNotRetireOwner() {
  let releaseFirst;
  class BlockingAdapter extends RecordingAdapter {
    async setLocalSource(source, enabled) {
      this.calls.push(["setLocalSource", source, enabled]);
      await new Promise((resolve) => { releaseFirst = resolve; });
    }
  }
  const runtime = loadRuntime(BlockingAdapter);
  const transaction = "host-" + "5".repeat(32);
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "set_local_source",
    source: "camera",
    enabled: true
  }, false);
  const retired = [];

  async function invoke(command, payload) {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_dispatched") {
      return {
        kind: "provider-ready",
        payload: { transaction_id: payload.transaction_id }
      };
    }
    if (command === "media.provider_not_started") {
      retired.push(payload.transaction_id);
      return { kind: "error", payload: { message: "retired" } };
    }
    if (command === "media.provider_effect_success") {
      return { kind: "media-updated", payload: { snapshot: {} } };
    }
    throw new Error("unexpected command " + command);
  }

  const firstPromise = runtime.execute(event, invoke);
  while (typeof releaseFirst !== "function") {
    await new Promise((resolve) => setImmediate(resolve));
  }
  const duplicate = await runtime.execute(event, invoke);
  assert.equal(duplicate.kind, "status");
  assert.equal(duplicate.payload !== null && typeof duplicate.payload === "object", true);
  assert.equal(Object.keys(duplicate.payload).length, 0);
  assert.deepEqual(retired, []);

  releaseFirst();
  const firstResult = await firstPromise;
  assert.equal(firstResult.kind, "media-updated");
  assert.deepEqual(retired, []);
  assert.equal(RecordingAdapter.instances[0].calls.length, 1);
  assert.equal(runtime._activeTransaction, null);
  assert.equal(runtime._busy, false);
}

async function testConcurrentDispatchIsRetiredWithoutSecondProviderCall() {
  let releaseFirst;
  class BlockingAdapter extends RecordingAdapter {
    async setLocalSource(source, enabled) {
      this.calls.push(["setLocalSource", source, enabled]);
      await new Promise((resolve) => { releaseFirst = resolve; });
    }
  }
  const runtime = loadRuntime(BlockingAdapter);
  const firstTx = "host-" + "6".repeat(32);
  const secondTx = "host-" + "7".repeat(32);
  const first = dispatch(firstTx, {
    transaction_id: firstTx,
    operation: "set_local_source",
    source: "camera",
    enabled: true
  }, false);
  const second = dispatch(secondTx, {
    transaction_id: secondTx,
    operation: "set_local_source",
    source: "microphone",
    enabled: true
  }, false);
  const retired = [];

  async function invoke(command, payload) {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_dispatched") {
      return {
        kind: "provider-ready",
        payload: { transaction_id: payload.transaction_id }
      };
    }
    if (command === "media.provider_not_started") {
      retired.push(payload.transaction_id);
      return { kind: "error", payload: { message: "busy" } };
    }
    if (command === "media.provider_effect_success") {
      return { kind: "media-updated", payload: { snapshot: {} } };
    }
    throw new Error("unexpected command " + command);
  }

  const firstPromise = runtime.execute(first, invoke);
  while (typeof releaseFirst !== "function") {
    await new Promise((resolve) => setImmediate(resolve));
  }
  const secondResult = await runtime.execute(second, invoke);
  assert.equal(secondResult.kind, "error");
  assert.deepEqual(retired, [secondTx]);
  releaseFirst();
  const firstResult = await firstPromise;
  assert.equal(firstResult.kind, "media-updated");
  assert.equal(RecordingAdapter.instances[0].calls.length, 1);
}


async function testMalformedConcurrentDispatchRetiresExactTransaction() {
  let releaseFirst;
  class BlockingAdapter extends RecordingAdapter {
    async setLocalSource(source, enabled) {
      this.calls.push(["setLocalSource", source, enabled]);
      await new Promise((resolve) => { releaseFirst = resolve; });
    }
  }
  const runtime = loadRuntime(BlockingAdapter);
  const firstTx = "host-" + "a".repeat(32);
  const malformedTx = "host-" + "b".repeat(32);
  const first = dispatch(firstTx, {
    transaction_id: firstTx,
    operation: "set_local_source",
    source: "camera",
    enabled: true
  }, false);
  const malformed = dispatch(malformedTx, {
    transaction_id: malformedTx,
    operation: "set_local_source",
    source: "not-a-source",
    enabled: true
  }, false);
  const retired = [];

  async function invoke(command, payload) {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_dispatched") {
      return {
        kind: "provider-ready",
        payload: { transaction_id: payload.transaction_id }
      };
    }
    if (command === "media.provider_not_started") {
      retired.push(payload.transaction_id);
      return { kind: "error", payload: { message: "retired" } };
    }
    if (command === "media.provider_effect_success") {
      return { kind: "media-updated", payload: { snapshot: {} } };
    }
    throw new Error("unexpected command " + command);
  }

  const firstPromise = runtime.execute(first, invoke);
  while (typeof releaseFirst !== "function") {
    await new Promise((resolve) => setImmediate(resolve));
  }

  const malformedResult = await runtime.execute(malformed, invoke);
  assert.equal(malformedResult.kind, "error");
  assert.deepEqual(retired, [malformedTx]);
  assert.equal(RecordingAdapter.instances[0].calls.length, 1);

  releaseFirst();
  const firstResult = await firstPromise;
  assert.equal(firstResult.kind, "media-updated");
  assert.equal(RecordingAdapter.instances[0].calls.length, 1);
}

async function testCleanProviderRebindRefreshesConfiguration() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const firstTx = "host-" + "8".repeat(32);
  const secondTx = "host-" + "9".repeat(32);
  let configCalls = 0;

  async function invoke(command, payload) {
    if (command === "media.provider_config") {
      configCalls += 1;
      return configCalls === 1
        ? configResult("wss://media-a.example.test", "moderation-a")
        : configResult("wss://media-b.example.test", "moderation-b");
    }
    if (command === "media.provider_dispatched") {
      return {
        kind: "provider-ready",
        payload: { transaction_id: payload.transaction_id }
      };
    }
    if (command === "media.provider_effect_success") {
      return { kind: "media-updated", payload: { snapshot: {} } };
    }
    throw new Error("unexpected command " + command);
  }

  const first = dispatch(firstTx, {
    transaction_id: firstTx,
    operation: "set_local_source",
    source: "camera",
    enabled: false
  }, false);
  const second = dispatch(secondTx, {
    transaction_id: secondTx,
    operation: "set_local_source",
    source: "camera",
    enabled: false
  }, false);

  assert.equal((await runtime.execute(first, invoke)).kind, "media-updated");
  assert.equal((await runtime.execute(second, invoke)).kind, "media-updated");
  assert.equal(configCalls, 2);
  assert.equal(RecordingAdapter.instances.length, 2);
  assert.equal(
    RecordingAdapter.instances[0].options.serverUrl,
    "wss://media-a.example.test"
  );
  assert.equal(
    RecordingAdapter.instances[1].options.serverUrl,
    "wss://media-b.example.test"
  );
  assert.equal(
    RecordingAdapter.instances[1].options.moderationParticipantIdentity,
    "moderation-b"
  );
}

async function testProviderRebindRejectsResidualDisconnectedState() {
  const residualCases = [
    { label: "stale room identity", mutation: { room_id: "stale-room" } },
    { label: "stale participant identity", mutation: { participant_id: "stale-participant" } },
    { label: "stale microphone publication", mutation: { microphone_enabled: true } },
    { label: "stale camera publication", mutation: { camera_enabled: true } },
    { label: "stale screen-share publication", mutation: { screen_share_enabled: true } },
    { label: "snapshot contract drift", mutation: { unexpected_state: true } }
  ];

  for (const testCase of residualCases) {
    RecordingAdapter.instances.length = 0;
    const runtime = loadRuntime(RecordingAdapter);
    const firstTx = "host-" + "c".repeat(32);
    const secondTx = "host-" + "d".repeat(32);
    let configCalls = 0;
    const retired = [];
    const providerDispatches = [];

    async function invoke(command, payload) {
      if (command === "media.provider_config") {
        configCalls += 1;
        return configCalls === 1
          ? configResult("wss://media-a.example.test", "moderation-a")
          : configResult("wss://media-b.example.test", "moderation-b");
      }
      if (command === "media.provider_dispatched") {
        providerDispatches.push(payload.transaction_id);
        return {
          kind: "provider-ready",
          payload: { transaction_id: payload.transaction_id }
        };
      }
      if (command === "media.provider_effect_success") {
        return { kind: "media-updated", payload: { snapshot: {} } };
      }
      if (command === "media.provider_not_started") {
        retired.push(payload.transaction_id);
        return { kind: "error", payload: { message: "sanitized" } };
      }
      throw new Error("unexpected command " + command);
    }

    const first = dispatch(firstTx, {
      transaction_id: firstTx,
      operation: "set_local_source",
      source: "camera",
      enabled: false
    }, false);
    const second = dispatch(secondTx, {
      transaction_id: secondTx,
      operation: "set_local_source",
      source: "camera",
      enabled: false
    }, false);

    assert.equal((await runtime.execute(first, invoke)).kind, "media-updated", testCase.label);
    Object.assign(RecordingAdapter.instances[0]._snapshot, testCase.mutation);

    const result = await runtime.execute(second, invoke);
    assert.equal(result.kind, "error", testCase.label);
    assert.deepEqual(retired, [secondTx], testCase.label);
    assert.deepEqual(providerDispatches, [firstTx], testCase.label);
    assert.equal(RecordingAdapter.instances.length, 1, testCase.label);
  }
}

async function testProviderRebindUnknownPriorStateSchedulesTeardown() {
  RecordingAdapter.instances.length = 0;

  class SnapshotFaultAdapter extends RecordingAdapter {
    snapshot() {
      if (this.failSnapshot === true) {
        throw new Error("prior provider state unavailable");
      }
      return super.snapshot();
    }
  }

  const runtime = loadRuntime(SnapshotFaultAdapter);
  const firstTx = "host-" + "3".repeat(32);
  const secondTx = "host-" + "4".repeat(32);
  let configCalls = 0;
  const retired = [];
  let transportCalls = 0;

  const invoke = async (command, payload) => {
    if (command === "media.provider_config") {
      configCalls += 1;
      return configCalls === 1
        ? configResult("wss://media-a.example.test", "moderation-a")
        : configResult("wss://media-b.example.test", "moderation-b");
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: payload.transaction_id } };
    }
    if (command === "media.provider_effect_success") {
      return { kind: "media-updated", payload: { snapshot: {} } };
    }
    if (command === "media.provider_not_started") {
      retired.push(payload.transaction_id);
      return { kind: "error", payload: { message: "retired" } };
    }
    if (command === "media.provider_transport_lost") {
      transportCalls += 1;
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      return { kind: "media-updated", payload: {} };
    }
    throw new Error("unexpected command " + command);
  };

  assert.equal((await runtime.execute(dispatch(firstTx, {
    transaction_id: firstTx,
    operation: "set_local_source",
    source: "camera",
    enabled: false
  }, false), invoke)).kind, "media-updated");

  const prior = RecordingAdapter.instances[0];
  prior.failSnapshot = true;
  const rejected = await runtime.execute(dispatch(secondTx, {
    transaction_id: secondTx,
    operation: "set_local_source",
    source: "camera",
    enabled: false
  }, false), invoke);

  assert.equal(rejected.kind, "error");
  assert.deepEqual(retired, [secondTx]);
  assert.equal(RecordingAdapter.instances.length, 1);
  assert.equal(runtime._cleanupRetryPending, true);

  // Teardown result itself is authoritative for provider cleanup; no second
  // snapshot read is required from the previously-faulting accessor.
  prior.failSnapshot = false;
  const reconciled = await runtime.reconcileTransport(invoke);
  assert.equal(reconciled.kind, "media-updated");
  assert.equal(transportCalls, 1);
  assert.equal(runtime._cleanupRetryPending, false);
  assert.equal(RecordingAdapter.instances.length, 1);
}

async function testProviderRebindCannotRetargetConnectedAdapter() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const sessionTx = "session-" + "a".repeat(32);
  const effectTx = "host-" + "b".repeat(32);
  let configCalls = 0;
  const retired = [];
  const providerDispatches = [];
  let transportLosses = 0;

  async function invoke(command, payload) {
    if (command === "media.provider_config") {
      configCalls += 1;
      return configCalls === 1
        ? configResult("wss://media-a.example.test", "moderation-a")
        : configResult("wss://media-b.example.test", "moderation-b");
    }
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: sessionTx,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "one-shot-secret"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      providerDispatches.push(payload.transaction_id);
      return {
        kind: "provider-ready",
        payload: { transaction_id: payload.transaction_id }
      };
    }
    if (command === "media.provider_session_success") {
      return { kind: "media-updated", payload: { snapshot: {} } };
    }
    if (command === "media.provider_not_started") {
      retired.push(payload.transaction_id);
      return { kind: "error", payload: { message: "sanitized" } };
    }
    if (command === "media.provider_transport_lost") {
      transportLosses += 1;
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      return { kind: "media-updated", payload: { snapshot: { connected: false } } };
    }
    throw new Error("unexpected command " + command);
  }

  const joined = dispatch(sessionTx, {
    transaction_id: sessionTx,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false);
  assert.equal((await runtime.execute(joined, invoke)).kind, "media-updated");
  assert.equal(runtime.snapshot().connected, true);

  const afterRebind = dispatch(effectTx, {
    transaction_id: effectTx,
    operation: "set_local_source",
    source: "camera",
    enabled: true
  }, false);
  const result = await runtime.execute(afterRebind, invoke);
  assert.equal(result.kind, "error");
  assert.deepEqual(retired, [effectTx]);
  assert.deepEqual(providerDispatches, [sessionTx]);
  assert.equal(RecordingAdapter.instances.length, 1);
  assert.equal(runtime._cleanupRetryPending, true);

  const reconciled = await runtime.reconcileTransport(invoke);
  assert.equal(reconciled.kind, "media-updated");
  assert.equal(transportLosses, 1);
  assert.equal(runtime._cleanupRetryPending, false);
  assert.equal(isCleanSnapshot(RecordingAdapter.instances[0].snapshot()), true);
  assert.equal(
    RecordingAdapter.instances[0].calls.filter((item) => item[0] === "disconnect").length,
    1
  );
}

async function testFailedReconnectCleanupRetriesWhileTrustedRecoveryRemainsLatched() {
  RecordingAdapter.instances.length = 0;

  class PartialReconnectAdapter extends RecordingAdapter {
    async reconnect(credential, enabledSources) {
      this.calls.push(["reconnect", credential, enabledSources]);
      this._snapshot = {
        connected: true,
        cleanup_required: false,
        room_id: credential.room_id,
        participant_id: credential.participant_id,
        microphone_enabled: true,
        camera_enabled: false,
        screen_share_enabled: false
      };
      this.failDisconnectOnce = true;
      throw new Error("provider camera republish failed");
    }
  }

  const runtime = loadRuntime(PartialReconnectAdapter);
  const transaction = "session-" + "c".repeat(32);
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "reconnect",
    credential_required: true,
    enabled_sources: ["microphone", "camera"]
  }, false);
  let transportCalls = 0;
  const invoke = async (command, payload) => {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: transaction,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "short-lived-token"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: transaction } };
    }
    if (command === "media.provider_failed") {
      return {
        kind: "error",
        payload: { message: "sanitized", recovery_required: true }
      };
    }
    if (command === "media.provider_transport_lost") {
      transportCalls += 1;
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      if (transportCalls === 1) {
        // Current #1201 requires trusted host reconciliation before browser
        // transport loss may clear an ambiguous provider recovery.
        return {
          kind: "error",
          payload: { message: "sanitized", recovery_required: true }
        };
      }
      return { kind: "media-updated", payload: {} };
    }
    throw new Error("unexpected command " + command);
  };

  const first = await runtime.execute(event, invoke);
  assert.equal(first.kind, "error");
  assert.equal(first.payload.recovery_required, true);
  const adapter = RecordingAdapter.instances[0];
  assert.equal(adapter.snapshot().connected, true);
  assert.equal(adapter.snapshot().microphone_enabled, true);
  assert.equal(
    adapter.calls.filter((item) => item[0] === "disconnect").length,
    1
  );

  const stillRecovering = await runtime.reconcileTransport(invoke);
  assert.equal(stillRecovering.kind, "error");
  assert.equal(stillRecovering.payload.recovery_required, true);
  assert.equal(isCleanSnapshot(adapter.snapshot()), true);
  assert.equal(
    adapter.calls.filter((item) => item[0] === "disconnect").length,
    2
  );
  assert.equal(transportCalls, 1);

  // Model the trusted Python recovery completion that happens outside browser
  // authority, then prove the retained clean snapshot can finally converge.
  runtime._transportRetryAt = 0;
  const converged = await runtime.reconcileTransport(invoke);
  assert.equal(converged.kind, "media-updated");
  assert.equal(transportCalls, 2);
  assert.equal(
    adapter.calls.filter((item) => item[0] === "disconnect").length,
    2
  );
  const duplicate = await runtime.reconcileTransport(async () => {
    throw new Error("clean transport convergence was duplicated");
  });
  assert.equal(duplicate, null);
}

async function testCleanupRetrySurvivesTemporarySnapshotFailure() {
  RecordingAdapter.instances.length = 0;

  class SnapshotBlindReconnectAdapter extends RecordingAdapter {
    constructor(options) {
      super(options);
      this.snapshotUnavailable = false;
    }

    snapshot() {
      if (this.snapshotUnavailable) {
        throw new Error("provider snapshot temporarily unavailable");
      }
      return super.snapshot();
    }

    async reconnect(credential, enabledSources) {
      this.calls.push(["reconnect", credential, enabledSources]);
      this._snapshot = {
        connected: true,
        cleanup_required: false,
        room_id: credential.room_id,
        participant_id: credential.participant_id,
        microphone_enabled: true,
        camera_enabled: false,
        screen_share_enabled: false
      };
      this.failDisconnectOnce = true;
      this.snapshotUnavailable = true;
      throw new Error("provider reconnect failed after microphone publication");
    }

    async disconnect() {
      this.calls.push(["disconnect"]);
      if (this.failDisconnectOnce === true) {
        this.failDisconnectOnce = false;
        throw new Error("provider cleanup failed");
      }
      // Return the exact teardown result while leaving the independent
      // snapshot() accessor unavailable. Runtime cleanup must consume this
      // completion proof directly instead of requiring a second provider read.
      this._snapshot = {
        connected: false,
        cleanup_required: false,
        room_id: null,
        participant_id: null,
        microphone_enabled: false,
        camera_enabled: false,
        screen_share_enabled: false
      };
      return Object.assign({}, this._snapshot);
    }
  }

  const runtime = loadRuntime(SnapshotBlindReconnectAdapter);
  const transaction = "session-" + "9".repeat(32);
  const event = dispatch(transaction, {
    transaction_id: transaction,
    operation: "reconnect",
    credential_required: true,
    enabled_sources: ["microphone"]
  }, false);
  let transportCalls = 0;
  const invoke = async (command, payload) => {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: transaction,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "short-lived-token"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: transaction } };
    }
    if (command === "media.provider_failed") {
      return {
        kind: "error",
        payload: { message: "sanitized", recovery_required: true }
      };
    }
    if (command === "media.provider_transport_lost") {
      transportCalls += 1;
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      return transportCalls === 1
        ? { kind: "error", payload: { recovery_required: true } }
        : { kind: "media-updated", payload: {} };
    }
    throw new Error("unexpected command " + command);
  };

  const failed = await runtime.execute(event, invoke);
  assert.equal(failed.kind, "error");
  assert.equal(failed.payload.recovery_required, true);
  assert.equal(runtime._transportLossSnapshot, null);
  assert.equal(runtime._cleanupRetryPending, true);

  const adapter = RecordingAdapter.instances[0];
  assert.equal(
    adapter.calls.filter((item) => item[0] === "disconnect").length,
    1
  );

  const cleanButRecovering = await runtime.reconcileTransport(invoke);
  assert.equal(cleanButRecovering.kind, "error");
  assert.equal(cleanButRecovering.payload.recovery_required, true);
  assert.equal(runtime._cleanupRetryPending, false);
  assert.equal(isCleanSnapshot(runtime._transportLossSnapshot), true);
  assert.equal(
    adapter.calls.filter((item) => item[0] === "disconnect").length,
    2
  );

  runtime._transportRetryAt = 0;
  const converged = await runtime.reconcileTransport(invoke);
  assert.equal(converged.kind, "media-updated");
  assert.equal(runtime._cleanupRetryPending, false);
  assert.equal(runtime._transportLossSnapshot, null);
}

async function testCleanupPendingPreemptsNewProviderMutation() {
  RecordingAdapter.instances.length = 0;

  class BlindCleanupAdapter extends RecordingAdapter {
    constructor(options) {
      super(options);
      this.snapshotUnavailable = false;
    }
    snapshot() {
      if (this.snapshotUnavailable) throw new Error("snapshot unavailable");
      return super.snapshot();
    }
    async reconnect(credential, enabledSources) {
      this.calls.push(["reconnect", credential, enabledSources]);
      this._snapshot = {
        connected: true,
        cleanup_required: false,
        room_id: credential.room_id,
        participant_id: credential.participant_id,
        microphone_enabled: true,
        camera_enabled: false,
        screen_share_enabled: false
      };
      this.failDisconnectOnce = true;
      this.snapshotUnavailable = true;
      throw new Error("reconnect partially applied");
    }
    async disconnect() {
      this.calls.push(["disconnect"]);
      if (this.failDisconnectOnce) {
        this.failDisconnectOnce = false;
        throw new Error("cleanup failed");
      }
      this.snapshotUnavailable = false;
      this._snapshot = {
        connected: false,
        cleanup_required: false,
        room_id: null,
        participant_id: null,
        microphone_enabled: false,
        camera_enabled: false,
        screen_share_enabled: false
      };
      return this.snapshot();
    }
  }

  const runtime = loadRuntime(BlindCleanupAdapter);
  const failedTx = "session-" + "8".repeat(32);
  const blockedTx = "host-" + "8".repeat(32);
  const providerCalls = [];
  const invoke = async (command, payload) => {
    providerCalls.push([command, payload.transaction_id || null]);
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: failedTx,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "short-lived-token"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: failedTx } };
    }
    if (command === "media.provider_failed") {
      return { kind: "error", payload: { recovery_required: true, transaction_id: failedTx } };
    }
    if (command === "media.provider_not_started") {
      assert.equal(payload.transaction_id, blockedTx);
      return { kind: "error", payload: { message: "retired" } };
    }
    if (command === "media.provider_transport_lost") {
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      return { kind: "error", payload: { recovery_required: true, transaction_id: failedTx } };
    }
    throw new Error("unexpected command " + command);
  };

  const failed = await runtime.execute(dispatch(failedTx, {
    transaction_id: failedTx,
    operation: "reconnect",
    credential_required: true,
    enabled_sources: ["microphone"]
  }, false), invoke);
  assert.equal(failed.payload.recovery_required, true);
  assert.equal(runtime._cleanupRetryPending, true);

  const blocked = await runtime.execute(dispatch(blockedTx, {
    transaction_id: blockedTx,
    operation: "set_local_source",
    source: "camera",
    enabled: true
  }, false), invoke);

  assert.equal(blocked.payload.recovery_required, true);
  assert.equal(
    RecordingAdapter.instances[0].calls.filter((item) => item[0] === "setLocalSource").length,
    0
  );
  assert.equal(
    providerCalls.filter(([command, tx]) =>
      command === "media.provider_not_started" && tx === blockedTx
    ).length,
    1
  );
  assert.equal(isCleanSnapshot(runtime._transportLossSnapshot), true);
}

async function testFailedDisconnectImmediateRetryCommitsOriginalLeave() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const connectTransaction = "session-" + "d".repeat(32);
  const disconnectTransaction = "session-" + "e".repeat(32);
  let activeTransaction = connectTransaction;
  const calls = [];
  const invoke = async (command, payload) => {
    calls.push([command, activeTransaction]);
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: activeTransaction,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "short-lived-token"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: activeTransaction } };
    }
    if (command === "media.provider_session_success") {
      assert.equal(payload.transaction_id, activeTransaction);
      return { kind: "media-updated", payload: {} };
    }
    if (command === "media.provider_failed") {
      throw new Error("clean disconnect retry must not enter recovery");
    }
    throw new Error("unexpected command " + command);
  };

  await runtime.execute(dispatch(connectTransaction, {
    transaction_id: connectTransaction,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false), invoke);

  const adapter = RecordingAdapter.instances[0];
  adapter.failDisconnectOnce = true;
  activeTransaction = disconnectTransaction;
  const result = await runtime.execute(dispatch(disconnectTransaction, {
    transaction_id: disconnectTransaction,
    operation: "disconnect",
    credential_required: false,
    enabled_sources: []
  }, false), invoke);

  assert.equal(result.kind, "media-updated");
  assert.equal(isCleanSnapshot(adapter.snapshot()), true);
  assert.equal(
    adapter.calls.filter((item) => item[0] === "disconnect").length,
    2
  );
  assert.equal(
    calls.filter(([command, tx]) =>
      command === "media.provider_session_success" && tx === disconnectTransaction
    ).length,
    1
  );
}

async function testCleanDisconnectRecoveryRetainsTransportFact() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const connectTransaction = "session-" + "a".repeat(32);
  const disconnectTransaction = "session-" + "b".repeat(32);
  let activeTransaction = connectTransaction;
  let transportCalls = 0;

  const invoke = async (command, payload) => {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: activeTransaction,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "short-lived-token"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: activeTransaction } };
    }
    if (command === "media.provider_session_success") {
      if (activeTransaction === connectTransaction) {
        return { kind: "media-updated", payload: {} };
      }
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      return {
        kind: "error",
        payload: { message: "sanitized", recovery_required: true }
      };
    }
    if (command === "media.provider_transport_lost") {
      transportCalls += 1;
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      return transportCalls === 1
        ? {
            kind: "error",
            payload: { message: "sanitized", recovery_required: true }
          }
        : { kind: "media-updated", payload: {} };
    }
    throw new Error("unexpected command " + command);
  };

  await runtime.execute(dispatch(connectTransaction, {
    transaction_id: connectTransaction,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false), invoke);

  const adapter = RecordingAdapter.instances[0];
  adapter.failDisconnectOnce = true;
  activeTransaction = disconnectTransaction;
  const failed = await runtime.execute(dispatch(disconnectTransaction, {
    transaction_id: disconnectTransaction,
    operation: "disconnect",
    credential_required: false,
    enabled_sources: []
  }, false), invoke);

  assert.equal(failed.kind, "error");
  assert.equal(failed.payload.recovery_required, true);
  assert.equal(isCleanSnapshot(adapter.snapshot()), true);
  assert.equal(isCleanSnapshot(runtime._transportLossSnapshot), true);

  const pending = await runtime.reconcileTransport(invoke);
  assert.equal(pending.kind, "error");
  assert.equal(pending.payload.recovery_required, true);
  assert.equal(transportCalls, 1);

  runtime._transportRetryAt = 0;
  const converged = await runtime.reconcileTransport(invoke);
  assert.equal(converged.kind, "media-updated");
  assert.equal(transportCalls, 2);
  assert.equal(runtime._transportLossSnapshot, null);
}

async function testMalformedCleanDisconnectAckFailsClosedAndRetainsSnapshot() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const connectTransaction = "session-" + "6".repeat(32);
  const disconnectTransaction = "session-" + "7".repeat(32);
  let activeTransaction = connectTransaction;
  let unknownCalls = 0;
  let transportCalls = 0;

  const invoke = async (command, payload) => {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: activeTransaction,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "short-lived-token"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: activeTransaction } };
    }
    if (command === "media.provider_session_success") {
      if (activeTransaction === connectTransaction) {
        return { kind: "media-updated", payload: {} };
      }
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      return null;
    }
    if (command === "media.provider_outcome_unknown") {
      unknownCalls += 1;
      assert.equal(payload.transaction_id, disconnectTransaction);
      return {
        kind: "error",
        payload: { message: "sanitized", recovery_required: true }
      };
    }
    if (command === "media.provider_transport_lost") {
      transportCalls += 1;
      assert.equal(isCleanSnapshot(payload.snapshot), true);
      return transportCalls === 1
        ? {
            kind: "error",
            payload: { message: "sanitized", recovery_required: true }
          }
        : { kind: "media-updated", payload: {} };
    }
    throw new Error("unexpected command " + command);
  };

  await runtime.execute(dispatch(connectTransaction, {
    transaction_id: connectTransaction,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false), invoke);

  const adapter = RecordingAdapter.instances[0];
  adapter.failDisconnectOnce = true;
  activeTransaction = disconnectTransaction;
  const failed = await runtime.execute(dispatch(disconnectTransaction, {
    transaction_id: disconnectTransaction,
    operation: "disconnect",
    credential_required: false,
    enabled_sources: []
  }, false), invoke);

  assert.equal(failed.kind, "error");
  assert.equal(failed.payload.recovery_required, true);
  assert.equal(unknownCalls, 1);
  assert.equal(isCleanSnapshot(adapter.snapshot()), true);
  assert.equal(isCleanSnapshot(runtime._transportLossSnapshot), true);

  const pending = await runtime.reconcileTransport(invoke);
  assert.equal(pending.kind, "error");
  assert.equal(pending.payload.recovery_required, true);
  runtime._transportRetryAt = 0;
  const converged = await runtime.reconcileTransport(invoke);
  assert.equal(converged.kind, "media-updated");
  assert.equal(runtime._transportLossSnapshot, null);
}

async function testTransportLossReconcilesExactlyOnce() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const transaction = "session-" + "c".repeat(32);
  const joined = dispatch(transaction, {
    transaction_id: transaction,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false);
  const calls = [];

  async function invoke(command, payload) {
    calls.push(command);
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: transaction,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "one-shot-secret"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: transaction } };
    }
    if (command === "media.provider_session_success") {
      return { kind: "media-updated", payload: { snapshot: { connected: true } } };
    }
    if (command === "media.provider_transport_lost") {
      assert.deepEqual(payload.snapshot, {
        connected: false,
        cleanup_required: false,
        room_id: null,
        participant_id: null,
        microphone_enabled: false,
        camera_enabled: false,
        screen_share_enabled: false
      });
      return { kind: "media-updated", payload: { snapshot: { connected: false } } };
    }
    throw new Error("unexpected bridge command " + command);
  }

  assert.equal((await runtime.execute(joined, invoke)).kind, "media-updated");
  RecordingAdapter.instances[0].loseTransport();

  const first = await runtime.reconcileTransport(invoke);
  const second = await runtime.reconcileTransport(invoke);
  assert.equal(first.kind, "media-updated");
  assert.equal(second, null);
  assert.equal(
    calls.filter((command) => command === "media.provider_transport_lost").length,
    1
  );
}

async function testPendingTransportLossRetiresNewMutationBeforeProviderCall() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const sessionTx = "session-" + "d".repeat(32);
  const joined = dispatch(sessionTx, {
    transaction_id: sessionTx,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false);
  let joinedComplete = false;

  async function joinInvoke(command, payload) {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: sessionTx,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "one-shot-secret"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: payload.transaction_id } };
    }
    if (command === "media.provider_session_success") {
      joinedComplete = true;
      return { kind: "media-updated", payload: { snapshot: { connected: true } } };
    }
    throw new Error("unexpected join command " + command);
  }

  await runtime.execute(joined, joinInvoke);
  assert.equal(joinedComplete, true);
  const adapter = RecordingAdapter.instances[0];
  adapter.loseTransport();

  const mutationTx = "host-" + "e".repeat(32);
  const mutation = dispatch(mutationTx, {
    transaction_id: mutationTx,
    operation: "set_local_source",
    source: "camera",
    enabled: true
  }, false);
  const calls = [];

  const result = await runtime.execute(mutation, async (command, payload) => {
    calls.push(command);
    if (command === "media.provider_not_started") {
      assert.equal(payload.transaction_id, mutationTx);
      return { kind: "error", payload: { message: "retired" } };
    }
    if (command === "media.provider_transport_lost") {
      assert.equal(payload.snapshot.connected, false);
      return { kind: "media-updated", payload: { snapshot: { connected: false } } };
    }
    throw new Error("unexpected reconciliation command " + command);
  });

  assert.equal(result.kind, "media-updated");
  assert.deepEqual(calls, [
    "media.provider_not_started",
    "media.provider_transport_lost"
  ]);
  assert.equal(
    adapter.calls.filter((item) => item[0] === "setLocalSource").length,
    0
  );
}

async function testTransportLossBridgeReplyLossRetriesSameSnapshot() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const sessionTx = "session-" + "f".repeat(32);
  const joined = dispatch(sessionTx, {
    transaction_id: sessionTx,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false);

  await runtime.execute(joined, async (command, payload) => {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: sessionTx,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "one-shot-secret"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: payload.transaction_id } };
    }
    if (command === "media.provider_session_success") {
      return { kind: "media-updated", payload: { snapshot: { connected: true } } };
    }
    throw new Error("unexpected join command " + command);
  });

  RecordingAdapter.instances[0].loseTransport();
  const snapshots = [];
  const first = await runtime.reconcileTransport(async (command, payload) => {
    assert.equal(command, "media.provider_transport_lost");
    snapshots.push(JSON.stringify(payload.snapshot));
    throw new Error("bridge response lost after Python reconciliation");
  });
  assert.equal(first, null);

  let earlyRetryCalls = 0;
  const second = await runtime.reconcileTransport(async () => {
    earlyRetryCalls += 1;
    throw new Error("transport retry cooldown was bypassed");
  });
  assert.equal(second, null);
  assert.equal(earlyRetryCalls, 0);

  // Advance only the runtime's retry gate; the provider snapshot must remain
  // exactly the same until Python gives a terminal acknowledgement.
  runtime._transportRetryAt = 0;
  const third = await runtime.reconcileTransport(async (command, payload) => {
    assert.equal(command, "media.provider_transport_lost");
    snapshots.push(JSON.stringify(payload.snapshot));
    return { kind: "media-updated", payload: { snapshot: { connected: false } } };
  });
  assert.equal(third.kind, "media-updated");
  assert.equal(snapshots.length, 2);
  assert.equal(snapshots[0], snapshots[1]);
}

async function testTransportLossGenericErrorIsNotTerminal() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const sessionTx = "session-" + "2".repeat(32);
  const joined = dispatch(sessionTx, {
    transaction_id: sessionTx,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false);

  await runtime.execute(joined, async (command, payload) => {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: sessionTx,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "one-shot-secret"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: payload.transaction_id } };
    }
    if (command === "media.provider_session_success") {
      return { kind: "media-updated", payload: { snapshot: { connected: true } } };
    }
    throw new Error("unexpected join command " + command);
  });

  RecordingAdapter.instances[0].loseTransport();
  let transportCalls = 0;
  const first = await runtime.reconcileTransport(async (command) => {
    assert.equal(command, "media.provider_transport_lost");
    transportCalls += 1;
    return { kind: "error", payload: { message: "temporary bridge failure" } };
  });
  assert.equal(first.kind, "error");
  assert.equal(transportCalls, 1);

  const blockedRetry = await runtime.reconcileTransport(async () => {
    transportCalls += 1;
    throw new Error("generic error incorrectly cleared retry cooldown");
  });
  assert.equal(blockedRetry, null);
  assert.equal(transportCalls, 1);

  runtime._transportRetryAt = 0;
  const recovery = await runtime.reconcileTransport(async (command) => {
    assert.equal(command, "media.provider_transport_lost");
    transportCalls += 1;
    return {
      kind: "error",
      payload: {
        recovery_required: true,
        transaction_id: "session-" + "3".repeat(32)
      }
    };
  });
  assert.equal(recovery.kind, "error");
  assert.equal(recovery.payload.recovery_required, true);
  assert.equal(transportCalls, 2);

  const recoveryCooldown = await runtime.reconcileTransport(async () => {
    transportCalls += 1;
    throw new Error("recovery retry cooldown was bypassed");
  });
  assert.equal(recoveryCooldown, null);
  assert.equal(transportCalls, 2);

  // Recovery is only the provider/canonical uncertainty latch.  The provider is
  // still cleanly disconnected, so preserve that fact until Python later
  // accepts and commits the canonical transport loss.
  runtime._transportRetryAt = 0;
  const accepted = await runtime.reconcileTransport(async (command, payload) => {
    assert.equal(command, "media.provider_transport_lost");
    assert.equal(payload.snapshot.connected, false);
    transportCalls += 1;
    return { kind: "media-updated", payload: { snapshot: { connected: false } } };
  });
  assert.equal(accepted.kind, "media-updated");
  assert.equal(transportCalls, 3);

  const afterAccepted = await runtime.reconcileTransport(async () => {
    transportCalls += 1;
    throw new Error("accepted transport loss was not cleared");
  });
  assert.equal(afterAccepted, null);
  assert.equal(transportCalls, 3);
}

async function testMovedRoomCleanupRetriesBeforePythonTransportLoss() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const sessionTx = "session-" + "1".repeat(32);
  const joined = dispatch(sessionTx, {
    transaction_id: sessionTx,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  }, false);

  await runtime.execute(joined, async (command, payload) => {
    if (command === "media.provider_config") return configResult();
    if (command === "media.provider_take_credential") {
      return {
        kind: "provider-credential",
        payload: {
          transaction_id: sessionTx,
          credential: {
            room_id: "room-1",
            participant_id: "student-1",
            token: "one-shot-secret"
          }
        }
      };
    }
    if (command === "media.provider_dispatched") {
      return { kind: "provider-ready", payload: { transaction_id: payload.transaction_id } };
    }
    if (command === "media.provider_session_success") {
      return { kind: "media-updated", payload: { snapshot: { connected: true } } };
    }
    throw new Error("unexpected join command " + command);
  });

  const adapter = RecordingAdapter.instances[0];
  adapter.moveTransport();
  adapter.failDisconnectOnce = true;
  let pythonCalls = 0;

  const first = await runtime.reconcileTransport(async () => {
    pythonCalls += 1;
    throw new Error("Python must not see unclean provider move");
  });
  assert.equal(first, null);
  assert.equal(pythonCalls, 0);
  assert.equal(adapter.snapshot().cleanup_required, true);
  assert.equal(
    adapter.calls.filter((item) => item[0] === "disconnect").length,
    1
  );

  const second = await runtime.reconcileTransport(async () => {
    pythonCalls += 1;
    throw new Error("cleanup retry cooldown was bypassed");
  });
  assert.equal(second, null);
  assert.equal(pythonCalls, 0);
  assert.equal(
    adapter.calls.filter((item) => item[0] === "disconnect").length,
    1
  );

  runtime._transportRetryAt = 0;
  const third = await runtime.reconcileTransport(async (command, payload) => {
    pythonCalls += 1;
    assert.equal(command, "media.provider_transport_lost");
    assert.equal(payload.snapshot.connected, false);
    assert.equal(payload.snapshot.cleanup_required, false);
    return { kind: "media-updated", payload: { snapshot: { connected: false } } };
  });
  assert.equal(third.kind, "media-updated");
  assert.equal(pythonCalls, 1);
  assert.equal(
    adapter.calls.filter((item) => item[0] === "disconnect").length,
    2
  );
}

async function run() {
  await testMultiChunkMarksProviderBoundaryOnce();
  await testJoinTakesCredentialBeforeDispatchAndReturnsExactSnapshot();
  await testMissingRuntimeConfigurationRetiresBeforeDispatch();
  await testCleanConnectFailureUsesExactCleanFailureCallback();
  await testMalformedCleanConnectAckFailsClosedAndRetainsSnapshot();
  await testProviderEffectFailureRequiresRecoveryCallback();
  await testProviderSuccessAckLossRequiresRecovery();
  await testCrossedTransactionConfigurationLossRequiresRecovery();
  await testMalformedSessionInstructionRetiresBeforeCredentialHandoff();
  await testCoercedProviderFieldsRetireBeforeProviderBoundary();
  await testMalformedCrossedInstructionEscalatesToUnknownRecovery();
  await testMalformedModerationRetiresBeforeProviderBoundary();
  await testMalformedDeviceRecoveryRetiresBeforeProviderBoundary();
  await testDuplicateInflightDispatchDoesNotRetireOwner();
  await testConcurrentDispatchIsRetiredWithoutSecondProviderCall();
  await testMalformedConcurrentDispatchRetiresExactTransaction();
  await testCleanProviderRebindRefreshesConfiguration();
  await testProviderRebindRejectsResidualDisconnectedState();
  await testProviderRebindUnknownPriorStateSchedulesTeardown();
  await testProviderRebindCannotRetargetConnectedAdapter();
  await testFailedReconnectCleanupRetriesWhileTrustedRecoveryRemainsLatched();
  await testCleanupRetrySurvivesTemporarySnapshotFailure();
  await testCleanupPendingPreemptsNewProviderMutation();
  await testFailedDisconnectImmediateRetryCommitsOriginalLeave();
  await testCleanDisconnectRecoveryRetainsTransportFact();
  await testMalformedCleanDisconnectAckFailsClosedAndRetainsSnapshot();
  await testTransportLossReconcilesExactlyOnce();
  await testPendingTransportLossRetiresNewMutationBeforeProviderCall();
  await testTransportLossBridgeReplyLossRetriesSameSnapshot();
  await testTransportLossGenericErrorIsNotTerminal();
  await testMovedRoomCleanupRetriesBeforePythonTransportLoss();
  console.log("LIVEKIT_CLASSROOM_MEDIA_TRANSACTION_RUNTIME=PASS");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
