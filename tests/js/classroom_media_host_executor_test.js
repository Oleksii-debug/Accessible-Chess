"use strict";

const assert = require("assert");
const {
  ClassroomMediaHostExecutor,
  ClassroomMediaHostExecutorError
} = require("../web/classroom_media_host_executor.js");

const HOST_ID = "host-" + "1".repeat(32);
const SESSION_ID = "session-" + "2".repeat(32);
const TOKEN = "one-shot-secret-token";

function snapshot(overrides) {
  return Object.assign({
    connected: true,
    cleanup_required: false,
    room_id: "room-1",
    participant_id: "student-1",
    microphone_enabled: false,
    camera_enabled: false,
    screen_share_enabled: false
  }, overrides || {});
}

class FakeAdapter {
  constructor() {
    this.calls = [];
    this.current = snapshot();
    this.fail = new Set();
    this.connectGate = null;
  }

  async connect(credential, enabledSources) {
    this.calls.push(["connect", credential, enabledSources.slice()]);
    if (this.connectGate) await this.connectGate;
    if (this.fail.has("connect")) throw new Error("private connect detail " + TOKEN);
    this.current = snapshot({
      connected: true,
      room_id: credential.room_id,
      participant_id: credential.participant_id,
      microphone_enabled: enabledSources.includes("microphone"),
      camera_enabled: enabledSources.includes("camera"),
      screen_share_enabled: enabledSources.includes("screen_share")
    });
    return this.current;
  }

  async reconnect(credential, enabledSources) {
    this.calls.push(["reconnect", credential, enabledSources.slice()]);
    if (this.fail.has("reconnect")) throw new Error("private reconnect detail " + TOKEN);
    this.current = snapshot({
      connected: true,
      room_id: credential.room_id,
      participant_id: credential.participant_id,
      microphone_enabled: enabledSources.includes("microphone"),
      camera_enabled: enabledSources.includes("camera"),
      screen_share_enabled: enabledSources.includes("screen_share")
    });
    return this.current;
  }

  async disconnect() {
    this.calls.push(["disconnect"]);
    if (this.fail.has("disconnect")) throw new Error("private disconnect detail");
    this.current = snapshot({
      connected: false,
      room_id: null,
      participant_id: null,
      microphone_enabled: false,
      camera_enabled: false,
      screen_share_enabled: false
    });
    return this.current;
  }

  async setLocalSource(source, enabled) {
    this.calls.push(["setLocalSource", source, enabled]);
    if (this.fail.has("setLocalSource")) throw new Error("private source detail");
    const updates = {};
    updates[source === "microphone"
      ? "microphone_enabled"
      : source === "camera"
        ? "camera_enabled"
        : "screen_share_enabled"] = enabled;
    this.current = snapshot(Object.assign({}, this.current, updates));
    return this.current;
  }

  async applyModeration(commands) {
    this.calls.push(["applyModeration", commands]);
    if (this.fail.has("applyModeration")) throw new Error("private rpc detail");
  }

  async recoverDevice(kind, deviceId, republish) {
    this.calls.push(["recoverDevice", kind, deviceId, republish]);
    if (this.fail.has("recoverDevice")) throw new Error("private device detail");
    return this.current;
  }

  snapshot() {
    if (this.fail.has("snapshot")) throw new Error("private snapshot detail");
    return this.current;
  }
}

function create(adapter, takeCredential) {
  return new ClassroomMediaHostExecutor({
    adapter,
    takeCredential: takeCredential || (async () => ({
      room_id: "room-1",
      participant_id: "student-1",
      token: TOKEN
    }))
  });
}

async function expectReject(promise, pattern) {
  let error = null;
  try {
    await promise;
  } catch (caught) {
    error = caught;
  }
  assert(error instanceof ClassroomMediaHostExecutorError);
  assert(pattern.test(error.message), error.message);
  return error;
}

async function testLocalSourceReceipt() {
  const adapter = new FakeAdapter();
  const executor = create(adapter);
  const result = await executor.execute({
    transaction_id: HOST_ID,
    operation: "set_local_source",
    source: "microphone",
    enabled: true
  });
  assert.deepStrictEqual(adapter.calls, [
    ["setLocalSource", "microphone", true]
  ]);
  assert.strictEqual(result.status, "success");
  assert.strictEqual(result.chunk_index, null);
  assert.strictEqual(result.provider_snapshot.microphone_enabled, true);
  assert.strictEqual(result.transaction_id, HOST_ID);
}

async function testModerationChunkReceipt() {
  const adapter = new FakeAdapter();
  const executor = create(adapter);
  const commands = [{
    operation_id: "op-1",
    actor_id: "teacher-1",
    target_id: "student-1",
    action: "soft_mute",
    source: "microphone",
    value: true
  }];
  const result = await executor.execute({
    transaction_id: HOST_ID,
    operation: "apply_moderation",
    chunk_index: 1,
    chunk_count: 3,
    commands
  });
  assert.strictEqual(adapter.calls.length, 1);
  assert.strictEqual(adapter.calls[0][0], "applyModeration");
  assert.deepStrictEqual(adapter.calls[0][1], commands);
  assert.strictEqual(result.status, "success");
  assert.strictEqual(result.chunk_index, 1);
  assert.strictEqual(result.provider_snapshot.connected, true);
}

async function testDeviceRecoveryReceipt() {
  const adapter = new FakeAdapter();
  const executor = create(adapter);
  const result = await executor.execute({
    transaction_id: HOST_ID,
    operation: "recover_device",
    kind: "camera",
    device_id: "camera-2",
    republish_enabled: true
  });
  assert.deepStrictEqual(adapter.calls, [
    ["recoverDevice", "camera", "camera-2", true]
  ]);
  assert.strictEqual(result.status, "success");
}

async function testConnectUsesCredentialOnceAndNeverReturnsSecret() {
  const adapter = new FakeAdapter();
  let handoffs = 0;
  const executor = create(adapter, async (transactionId) => {
    handoffs += 1;
    assert.strictEqual(transactionId, SESSION_ID);
    return {
      room_id: "room-1",
      participant_id: "student-1",
      token: TOKEN
    };
  });
  const result = await executor.execute({
    transaction_id: SESSION_ID,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  });
  assert.strictEqual(handoffs, 1);
  assert.strictEqual(adapter.calls.length, 1);
  assert.strictEqual(adapter.calls[0][0], "connect");
  assert.deepStrictEqual(adapter.calls[0][2], []);
  assert.strictEqual(result.status, "success");
  assert.strictEqual(result.provider_snapshot.microphone_enabled, false);
  assert.strictEqual(result.provider_snapshot.camera_enabled, false);
  assert(!JSON.stringify(result).includes(TOKEN));
  assert(!JSON.stringify(executor).includes(TOKEN));
}

async function testReconnectPreservesExactEnabledSources() {
  const adapter = new FakeAdapter();
  const executor = create(adapter);
  const result = await executor.execute({
    transaction_id: SESSION_ID,
    operation: "reconnect",
    credential_required: true,
    enabled_sources: ["microphone", "camera"]
  });
  assert.deepStrictEqual(adapter.calls[0][2], ["microphone", "camera"]);
  assert.strictEqual(result.provider_snapshot.microphone_enabled, true);
  assert.strictEqual(result.provider_snapshot.camera_enabled, true);
  assert.strictEqual(result.provider_snapshot.screen_share_enabled, false);
}

async function testDisconnectDoesNotRequestCredential() {
  const adapter = new FakeAdapter();
  let handoffs = 0;
  const executor = create(adapter, async () => {
    handoffs += 1;
    throw new Error("must not be called");
  });
  const result = await executor.execute({
    transaction_id: SESSION_ID,
    operation: "disconnect",
    credential_required: false,
    enabled_sources: []
  });
  assert.strictEqual(handoffs, 0);
  assert.deepStrictEqual(adapter.calls, [["disconnect"]]);
  assert.strictEqual(result.provider_snapshot.connected, false);
  assert.strictEqual(result.provider_snapshot.cleanup_required, false);
}

async function testConnectSemanticSnapshotMismatchFailsClosed() {
  const adapter = new FakeAdapter();
  adapter.connect = async function (credential, enabledSources) {
    this.calls.push(["connect", credential, enabledSources.slice()]);
    this.current = snapshot({
      connected: true,
      room_id: credential.room_id,
      participant_id: "different-participant"
    });
    return this.current;
  };
  const executor = create(adapter);
  const result = await executor.execute({
    transaction_id: SESSION_ID,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  });
  assert.strictEqual(result.status, "failed");
  assert.strictEqual(result.provider_snapshot.participant_id, "different-participant");
  assert(!JSON.stringify(result).includes(TOKEN));
}

async function testReconnectSourceSnapshotMismatchFailsClosed() {
  const adapter = new FakeAdapter();
  adapter.reconnect = async function (credential, enabledSources) {
    this.calls.push(["reconnect", credential, enabledSources.slice()]);
    this.current = snapshot({
      connected: true,
      room_id: credential.room_id,
      participant_id: credential.participant_id,
      microphone_enabled: false,
      camera_enabled: false,
      screen_share_enabled: false
    });
    return this.current;
  };
  const executor = create(adapter);
  const result = await executor.execute({
    transaction_id: SESSION_ID,
    operation: "reconnect",
    credential_required: true,
    enabled_sources: ["microphone"]
  });
  assert.strictEqual(result.status, "failed");
  assert.strictEqual(result.provider_snapshot.microphone_enabled, false);
}

async function testDirtyDisconnectSnapshotFailsClosed() {
  const adapter = new FakeAdapter();
  adapter.disconnect = async function () {
    this.calls.push(["disconnect"]);
    this.current = snapshot({
      connected: false,
      cleanup_required: false,
      room_id: null,
      participant_id: null,
      microphone_enabled: true,
      camera_enabled: false,
      screen_share_enabled: false
    });
    return this.current;
  };
  const executor = create(adapter);
  const result = await executor.execute({
    transaction_id: SESSION_ID,
    operation: "disconnect",
    credential_required: false,
    enabled_sources: []
  });
  assert.strictEqual(result.status, "failed");
  assert.strictEqual(result.provider_snapshot.microphone_enabled, true);
}

async function testConnectFailureReturnsSanitizedCleanSnapshot() {
  const adapter = new FakeAdapter();
  adapter.fail.add("connect");
  adapter.current = snapshot({
    connected: false,
    room_id: null,
    participant_id: null
  });
  const executor = create(adapter);
  const result = await executor.execute({
    transaction_id: SESSION_ID,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  });
  assert.strictEqual(result.status, "failed");
  assert.strictEqual(result.provider_snapshot.connected, false);
  assert.strictEqual(result.provider_snapshot.cleanup_required, false);
  assert(!JSON.stringify(result).includes("private connect detail"));
  assert(!JSON.stringify(result).includes(TOKEN));
}

async function testConnectFailureWithCleanupRequiredIsVisibleWithoutSecret() {
  const adapter = new FakeAdapter();
  adapter.fail.add("connect");
  adapter.current = snapshot({
    connected: false,
    cleanup_required: true,
    room_id: null,
    participant_id: null
  });
  const executor = create(adapter);
  const result = await executor.execute({
    transaction_id: SESSION_ID,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  });
  assert.strictEqual(result.status, "failed");
  assert.strictEqual(result.provider_snapshot.cleanup_required, true);
  assert(!JSON.stringify(result).includes(TOKEN));
}

async function testProviderFailureWithoutValidSnapshotReturnsNullSnapshot() {
  const adapter = new FakeAdapter();
  adapter.fail.add("setLocalSource");
  adapter.fail.add("snapshot");
  const executor = create(adapter);
  const result = await executor.execute({
    transaction_id: HOST_ID,
    operation: "set_local_source",
    source: "camera",
    enabled: true
  });
  assert.strictEqual(result.status, "failed");
  assert.strictEqual(result.provider_snapshot, null);
}

async function testMalformedSuccessSnapshotBecomesFailedReceipt() {
  const adapter = new FakeAdapter();
  adapter.setLocalSource = async function (source, enabled) {
    this.calls.push(["setLocalSource", source, enabled]);
    return { connected: true };
  };
  const executor = create(adapter);
  const result = await executor.execute({
    transaction_id: HOST_ID,
    operation: "set_local_source",
    source: "camera",
    enabled: true
  });
  assert.strictEqual(result.status, "failed");
  assert.strictEqual(result.provider_snapshot.connected, true);
}

async function testCredentialHandoffFailureNeverCallsProvider() {
  const adapter = new FakeAdapter();
  const executor = create(adapter, async () => {
    throw new Error("private handoff detail " + TOKEN);
  });
  const error = await expectReject(
    executor.execute({
      transaction_id: SESSION_ID,
      operation: "connect",
      credential_required: true,
      enabled_sources: []
    }),
    /credential handoff failed/
  );
  assert.deepStrictEqual(adapter.calls, []);
  assert(!String(error).includes(TOKEN));
}

async function testInvalidPayloadNeverCallsProviderOrCredentialLoader() {
  const adapter = new FakeAdapter();
  let handoffs = 0;
  const executor = create(adapter, async () => {
    handoffs += 1;
    return {
      room_id: "room-1",
      participant_id: "student-1",
      token: TOKEN
    };
  });
  await expectReject(
    executor.execute({
      transaction_id: SESSION_ID,
      operation: "connect",
      credential_required: true,
      enabled_sources: ["microphone"]
    }),
    /initial join cannot auto-publish/
  );
  assert.strictEqual(handoffs, 0);
  assert.deepStrictEqual(adapter.calls, []);
}

async function testUnexpectedFieldsAreRejectedBeforeProvider() {
  const adapter = new FakeAdapter();
  const executor = create(adapter);
  await expectReject(
    executor.execute({
      transaction_id: HOST_ID,
      operation: "set_local_source",
      source: "camera",
      enabled: true,
      extra: "not-allowed"
    }),
    /fields are invalid/
  );
  assert.deepStrictEqual(adapter.calls, []);
}

async function testModerationChunkBoundsAreEnforcedBeforeProvider() {
  const adapter = new FakeAdapter();
  const executor = create(adapter);
  await expectReject(
    executor.execute({
      transaction_id: HOST_ID,
      operation: "apply_moderation",
      chunk_index: 2,
      chunk_count: 2,
      commands: [{}]
    }),
    /chunk position is invalid/
  );
  await expectReject(
    executor.execute({
      transaction_id: HOST_ID,
      operation: "apply_moderation",
      chunk_index: 0,
      chunk_count: 2,
      commands: Array.from({ length: 25 }, () => ({}))
    }),
    /command chunk is invalid/
  );
  assert.deepStrictEqual(adapter.calls, []);
}

async function testExecutorSingleFlightRejectsOverlap() {
  const adapter = new FakeAdapter();
  let release;
  adapter.connectGate = new Promise((resolve) => { release = resolve; });
  const executor = create(adapter);
  const first = executor.execute({
    transaction_id: SESSION_ID,
    operation: "connect",
    credential_required: true,
    enabled_sources: []
  });

  await Promise.resolve();
  await Promise.resolve();
  assert.strictEqual(executor.busy, true);
  await expectReject(
    executor.execute({
      transaction_id: HOST_ID,
      operation: "set_local_source",
      source: "camera",
      enabled: true
    }),
    /already has an active transaction/
  );

  release();
  const result = await first;
  assert.strictEqual(result.status, "success");
  assert.strictEqual(executor.busy, false);
}

async function testCredentialShapeIsStrict() {
  const adapter = new FakeAdapter();
  const executor = create(adapter, async () => ({
    room_id: "room-1",
    participant_id: "student-1",
    token: TOKEN,
    leaked_extra: true
  }));
  await expectReject(
    executor.execute({
      transaction_id: SESSION_ID,
      operation: "connect",
      credential_required: true,
      enabled_sources: []
    }),
    /credential handoff failed/
  );
  assert.deepStrictEqual(adapter.calls, []);
}

async function main() {
  const tests = [
    testLocalSourceReceipt,
    testModerationChunkReceipt,
    testDeviceRecoveryReceipt,
    testConnectUsesCredentialOnceAndNeverReturnsSecret,
    testReconnectPreservesExactEnabledSources,
    testDisconnectDoesNotRequestCredential,
    testConnectSemanticSnapshotMismatchFailsClosed,
    testReconnectSourceSnapshotMismatchFailsClosed,
    testDirtyDisconnectSnapshotFailsClosed,
    testConnectFailureReturnsSanitizedCleanSnapshot,
    testConnectFailureWithCleanupRequiredIsVisibleWithoutSecret,
    testProviderFailureWithoutValidSnapshotReturnsNullSnapshot,
    testMalformedSuccessSnapshotBecomesFailedReceipt,
    testCredentialHandoffFailureNeverCallsProvider,
    testInvalidPayloadNeverCallsProviderOrCredentialLoader,
    testUnexpectedFieldsAreRejectedBeforeProvider,
    testModerationChunkBoundsAreEnforcedBeforeProvider,
    testExecutorSingleFlightRejectsOverlap,
    testCredentialShapeIsStrict
  ];
  for (const test of tests) {
    await test();
  }
  console.log("CLASSROOM_MEDIA_HOST_EXECUTOR_TESTS=PASS count=" + tests.length);
}

main().catch((error) => {
  console.error(
    "CLASSROOM_MEDIA_HOST_EXECUTOR_TESTS=FAIL",
    error && error.message ? error.message : String(error)
  );
  process.exitCode = 1;
});
