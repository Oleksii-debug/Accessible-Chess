"use strict";

const assert = require("assert");
const {
  ClassroomMediaHostExecutor
} = require("../web/classroom_media_host_executor.js");
const {
  ClassroomMediaProviderRuntime,
  ClassroomMediaProviderRuntimeError
} = require("../web/classroom_media_provider_runtime.js");

const SESSION_ID = "session-" + "1".repeat(32);
const HOST_ID = "host-" + "2".repeat(32);
const TOKEN = "one-shot-secret-token";

function snapshot(overrides) {
  return Object.assign({
    connected: false,
    cleanup_required: false,
    room_id: null,
    participant_id: null,
    microphone_enabled: false,
    camera_enabled: false,
    screen_share_enabled: false
  }, overrides || {});
}

class FakeAdapter {
  constructor(options) {
    this.options = options;
    this.calls = [];
    this.current = snapshot();
    this.failConnect = false;
    FakeAdapter.instances.push(this);
  }

  async connect(credential, enabledSources) {
    this.calls.push(["connect", credential.token, enabledSources.slice()]);
    if (this.failConnect) throw new Error("private provider detail " + TOKEN);
    this.current = snapshot({
      connected: true,
      room_id: credential.room_id,
      participant_id: credential.participant_id
    });
    return this.current;
  }

  async reconnect(credential, enabledSources) {
    this.calls.push(["reconnect", credential.token, enabledSources.slice()]);
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
    this.current = snapshot();
    return this.current;
  }

  async setLocalSource(source, enabled) {
    this.calls.push(["setLocalSource", source, enabled]);
    const updates = {};
    updates[
      source === "microphone"
        ? "microphone_enabled"
        : source === "camera"
          ? "camera_enabled"
          : "screen_share_enabled"
    ] = enabled;
    this.current = snapshot(Object.assign({}, this.current, updates));
    return this.current;
  }

  async applyModeration(commands) {
    this.calls.push(["applyModeration", commands]);
  }

  async recoverDevice(kind, deviceId, republishEnabled) {
    this.calls.push(["recoverDevice", kind, deviceId, republishEnabled]);
    return this.current;
  }

  snapshot() {
    return this.current;
  }
}
FakeAdapter.instances = [];

function runtimeGlobal() {
  return {
    LivekitClient: { Room: function Room() {} },
    AccessibleChessLiveKitMedia: {
      LiveKitClassroomMediaAdapter: FakeAdapter
    },
    AccessibleChessClassroomMediaHostExecutor: {
      ClassroomMediaHostExecutor
    }
  };
}

function providerConfigEvent() {
  return {
    kind: "provider-config",
    payload: {
      config: {
        server_url: "wss://media.example.test",
        moderation_participant_identity: "moderation-bot"
      }
    }
  };
}

function connectDispatch() {
  return {
    kind: "provider-dispatch",
    payload: {
      transaction_id: SESSION_ID,
      focus_target: "classroom-media-heading",
      provider: {
        transaction_id: SESSION_ID,
        operation: "connect",
        credential_required: true,
        enabled_sources: []
      }
    }
  };
}

function effectDispatch(chunkIndex, chunkCount) {
  return {
    kind: "provider-dispatch",
    payload: {
      transaction_id: HOST_ID,
      focus_target: "media-all-soft-mute",
      provider: {
        transaction_id: HOST_ID,
        operation: "apply_moderation",
        chunk_index: chunkIndex,
        chunk_count: chunkCount,
        commands: [{
          operation_id: "op-" + chunkIndex,
          actor_id: "teacher-1",
          target_id: "student-" + (chunkIndex + 1),
          action: "soft_mute",
          source: "microphone",
          value: true
        }]
      }
    }
  };
}

function terminalEvent() {
  return {
    kind: "media-updated",
    payload: {
      snapshot: null,
      announcement: "updated",
      focus_target: "classroom-media-heading",
      recovery_required: false
    }
  };
}

async function testConnectKeepsTokenInOneCredentialCallback() {
  FakeAdapter.instances.length = 0;
  const calls = [];
  const runtime = new ClassroomMediaProviderRuntime({
    globalObject: runtimeGlobal(),
    invoke: async function (command, payload) {
      calls.push([command, JSON.parse(JSON.stringify(payload || {}))]);
      if (command === "media.provider_config") return providerConfigEvent();
      if (command === "media.provider_take_credential") {
        assert.strictEqual(payload.transaction_id, SESSION_ID);
        return {
          kind: "provider-credential",
          payload: {
            transaction_id: SESSION_ID,
            credential: {
              room_id: "room-1",
              participant_id: "student-1",
              token: TOKEN
            }
          }
        };
      }
      if (command === "media.provider_dispatched") {
        return {
          kind: "provider-ready",
          payload: { transaction_id: SESSION_ID }
        };
      }
      if (command === "media.provider_session_success") {
        assert.deepStrictEqual(
          payload.snapshot,
          snapshot({
            connected: true,
            room_id: "room-1",
            participant_id: "student-1"
          })
        );
        return terminalEvent();
      }
      throw new Error("unexpected command " + command);
    }
  });

  const result = await runtime.settle(connectDispatch());

  assert.strictEqual(result.kind, "media-updated");
  assert.deepStrictEqual(
    calls.map((item) => item[0]),
    [
      "media.provider_config",
      "media.provider_take_credential",
      "media.provider_dispatched",
      "media.provider_session_success"
    ]
  );
  assert.strictEqual(FakeAdapter.instances.length, 1);
  assert.deepStrictEqual(
    FakeAdapter.instances[0].calls,
    [["connect", TOKEN, []]]
  );
  const publicCalls = JSON.stringify(
    calls.filter((item) => item[0] !== "media.provider_take_credential")
  );
  assert.doesNotMatch(publicCalls, new RegExp(TOKEN));
  assert.strictEqual(runtime.busy, false);
}

async function testModerationChunksStayInOneRuntimeTransaction() {
  FakeAdapter.instances.length = 0;
  const calls = [];
  let acknowledgements = 0;
  const runtime = new ClassroomMediaProviderRuntime({
    globalObject: runtimeGlobal(),
    invoke: async function (command, payload) {
      calls.push([command, payload]);
      if (command === "media.provider_config") return providerConfigEvent();
      if (command === "media.provider_dispatched") {
        return {
          kind: "provider-ready",
          payload: { transaction_id: HOST_ID }
        };
      }
      if (command === "media.provider_effect_success") {
        assert.strictEqual(payload.transaction_id, HOST_ID);
        assert.strictEqual(payload.chunk_index, acknowledgements);
        acknowledgements += 1;
        return acknowledgements === 1 ? effectDispatch(1, 2) : terminalEvent();
      }
      throw new Error("unexpected command " + command);
    }
  });

  const result = await runtime.settle(effectDispatch(0, 2));

  assert.strictEqual(result.kind, "media-updated");
  assert.strictEqual(acknowledgements, 2);
  assert.deepStrictEqual(
    calls.map((item) => item[0]),
    [
      "media.provider_config",
      "media.provider_dispatched",
      "media.provider_effect_success",
      "media.provider_dispatched",
      "media.provider_effect_success"
    ]
  );
  assert.deepStrictEqual(
    FakeAdapter.instances[0].calls.map((call) => call[0]),
    ["applyModeration", "applyModeration"]
  );
}

async function testUnavailablePackagedRuntimeCancelsBeforeProviderBoundary() {
  const calls = [];
  const runtime = new ClassroomMediaProviderRuntime({
    globalObject: {},
    invoke: async function (command, payload) {
      calls.push(command);
      if (command === "media.provider_config") return providerConfigEvent();
      if (command === "media.provider_not_started") {
        assert.strictEqual(payload.transaction_id, HOST_ID);
        return { kind: "error", payload: { message: "safe" } };
      }
      throw new Error("unexpected command " + command);
    }
  });

  const result = await runtime.settle(effectDispatch(0, 1));
  assert.strictEqual(result.kind, "error");
  assert.deepStrictEqual(calls, [
    "media.provider_config",
    "media.provider_not_started"
  ]);
}

async function testLostReadyAfterCredentialUsesFailClosedNotStartedCallback() {
  FakeAdapter.instances.length = 0;
  const calls = [];
  const runtime = new ClassroomMediaProviderRuntime({
    globalObject: runtimeGlobal(),
    invoke: async function (command, payload) {
      calls.push(command);
      if (command === "media.provider_config") return providerConfigEvent();
      if (command === "media.provider_take_credential") {
        return {
          kind: "provider-credential",
          payload: {
            transaction_id: SESSION_ID,
            credential: {
              room_id: "room-1",
              participant_id: "student-1",
              token: TOKEN
            }
          }
        };
      }
      if (command === "media.provider_dispatched") {
        throw new Error("lost local bridge response");
      }
      if (command === "media.provider_not_started") {
        assert.strictEqual(payload.transaction_id, SESSION_ID);
        return {
          kind: "error",
          payload: {
            message: "safe",
            recovery_required: true,
            transaction_id: SESSION_ID
          }
        };
      }
      throw new Error("unexpected command " + command);
    }
  });

  const result = await runtime.settle(connectDispatch());
  assert.strictEqual(result.kind, "error");
  assert.strictEqual(result.payload.recovery_required, true);
  assert.deepStrictEqual(calls, [
    "media.provider_config",
    "media.provider_take_credential",
    "media.provider_dispatched",
    "media.provider_not_started"
  ]);
  assert.deepStrictEqual(FakeAdapter.instances[0].calls, []);
}

async function testFailedConnectSubmitsExactCleanupSnapshot() {
  FakeAdapter.instances.length = 0;
  const calls = [];
  const globals = runtimeGlobal();
  class FailingAdapter extends FakeAdapter {
    constructor(options) {
      super(options);
      this.failConnect = true;
    }
  }
  globals.AccessibleChessLiveKitMedia = {
    LiveKitClassroomMediaAdapter: FailingAdapter
  };
  const runtime = new ClassroomMediaProviderRuntime({
    globalObject: globals,
    invoke: async function (command, payload) {
      calls.push(command);
      if (command === "media.provider_config") return providerConfigEvent();
      if (command === "media.provider_take_credential") {
        return {
          kind: "provider-credential",
          payload: {
            transaction_id: SESSION_ID,
            credential: {
              room_id: "room-1",
              participant_id: "student-1",
              token: TOKEN
            }
          }
        };
      }
      if (command === "media.provider_dispatched") {
        return {
          kind: "provider-ready",
          payload: { transaction_id: SESSION_ID }
        };
      }
      if (command === "media.provider_connection_failed_clean") {
        assert.deepStrictEqual(payload.snapshot, snapshot());
        return { kind: "error", payload: { message: "safe" } };
      }
      throw new Error("unexpected command " + command);
    }
  });

  const result = await runtime.settle(connectDispatch());
  assert.strictEqual(result.kind, "error");
  assert.deepStrictEqual(calls, [
    "media.provider_config",
    "media.provider_take_credential",
    "media.provider_dispatched",
    "media.provider_connection_failed_clean"
  ]);
}

async function testMismatchedExecutorReceiptEntersRecoveryWithoutCanonicalAck() {
  const calls = [];
  const globals = runtimeGlobal();
  globals.AccessibleChessClassroomMediaHostExecutor = {
    ClassroomMediaHostExecutor: class {
      constructor() {}
      async execute(payload) {
        return {
          transaction_id: payload.transaction_id,
          operation: payload.operation,
          status: "success",
          chunk_index: payload.chunk_index + 1,
          provider_snapshot: snapshot()
        };
      }
    }
  };
  const runtime = new ClassroomMediaProviderRuntime({
    globalObject: globals,
    invoke: async function (command, payload) {
      calls.push(command);
      if (command === "media.provider_config") return providerConfigEvent();
      if (command === "media.provider_dispatched") {
        return {
          kind: "provider-ready",
          payload: { transaction_id: HOST_ID }
        };
      }
      if (command === "media.provider_not_started") {
        assert.strictEqual(payload.transaction_id, HOST_ID);
        return {
          kind: "error",
          payload: {
            message: "safe",
            snapshot: null,
            recovery_required: true,
            transaction_id: HOST_ID
          }
        };
      }
      if (command === "media.provider_effect_success") {
        throw new Error("mismatched receipt must not acknowledge canonical effect");
      }
      throw new Error("unexpected command " + command);
    }
  });

  const result = await runtime.settle(effectDispatch(0, 2));

  assert.strictEqual(result.kind, "error");
  assert.strictEqual(result.payload.recovery_required, true);
  assert.deepStrictEqual(calls, [
    "media.provider_config",
    "media.provider_dispatched",
    "media.provider_not_started"
  ]);
}

async function testRuntimeRejectsConcurrentSettle() {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const runtime = new ClassroomMediaProviderRuntime({
    globalObject: runtimeGlobal(),
    invoke: async function (command) {
      if (command === "media.provider_config") {
        await gate;
        return providerConfigEvent();
      }
      if (command === "media.provider_not_started") {
        return { kind: "error", payload: { message: "safe" } };
      }
      throw new Error("unexpected command");
    }
  });

  const first = runtime.settle(effectDispatch(0, 1));
  await Promise.resolve();
  await assert.rejects(
    runtime.settle(effectDispatch(0, 1)),
    ClassroomMediaProviderRuntimeError
  );
  release();
  await first;
}

async function main() {
  await testConnectKeepsTokenInOneCredentialCallback();
  await testModerationChunksStayInOneRuntimeTransaction();
  await testUnavailablePackagedRuntimeCancelsBeforeProviderBoundary();
  await testLostReadyAfterCredentialUsesFailClosedNotStartedCallback();
  await testFailedConnectSubmitsExactCleanupSnapshot();
  await testMismatchedExecutorReceiptEntersRecoveryWithoutCanonicalAck();
  await testRuntimeRejectsConcurrentSettle();
  process.stdout.write("CLASSROOM_MEDIA_PROVIDER_RUNTIME_TEST=PASS\n");
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack || error) + "\n");
  process.exitCode = 1;
});
