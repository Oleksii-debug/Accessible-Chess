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

async function testProviderRebindCannotRetargetConnectedAdapter() {
  RecordingAdapter.instances.length = 0;
  const runtime = loadRuntime(RecordingAdapter);
  const sessionTx = "session-" + "a".repeat(32);
  const effectTx = "host-" + "b".repeat(32);
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

  const second = await runtime.reconcileTransport(async (command, payload) => {
    assert.equal(command, "media.provider_transport_lost");
    snapshots.push(JSON.stringify(payload.snapshot));
    return { kind: "media-updated", payload: { snapshot: { connected: false } } };
  });
  assert.equal(second.kind, "media-updated");
  assert.equal(snapshots.length, 2);
  assert.equal(snapshots[0], snapshots[1]);
}

async function run() {
  await testMultiChunkMarksProviderBoundaryOnce();
  await testJoinTakesCredentialBeforeDispatchAndReturnsExactSnapshot();
  await testMissingRuntimeConfigurationRetiresBeforeDispatch();
  await testCleanConnectFailureUsesExactCleanFailureCallback();
  await testProviderEffectFailureRequiresRecoveryCallback();
  await testProviderSuccessAckLossRequiresRecovery();
  await testCrossedTransactionConfigurationLossRequiresRecovery();
  await testMalformedSessionInstructionRetiresBeforeCredentialHandoff();
  await testMalformedCrossedInstructionEscalatesToUnknownRecovery();
  await testConcurrentDispatchIsRetiredWithoutSecondProviderCall();
  await testCleanProviderRebindRefreshesConfiguration();
  await testProviderRebindRejectsResidualDisconnectedState();
  await testProviderRebindCannotRetargetConnectedAdapter();
  await testTransportLossReconcilesExactlyOnce();
  await testPendingTransportLossRetiresNewMutationBeforeProviderCall();
  await testTransportLossBridgeReplyLossRetriesSameSnapshot();
  console.log("LIVEKIT_CLASSROOM_MEDIA_TRANSACTION_RUNTIME=PASS");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
