"use strict";

const {
  LiveKitClassroomMediaAdapter,
  LiveKitClassroomMediaError,
  DEFAULT_MODERATION_METHOD
} = require("../../web/livekit_classroom_media.js");

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function expectError(promiseFactory, messagePart) {
  return Promise.resolve()
    .then(promiseFactory)
    .then(
      () => { throw new Error("expected failure: " + messagePart); },
      (error) => {
        check(error instanceof LiveKitClassroomMediaError, "unexpected error type: " + String(error));
        check(error.message.includes(messagePart), "unexpected error message: " + error.message);
      }
    );
}

class FakeLocalParticipant {
  constructor(identity, owner) {
    this.identity = identity;
    this.owner = owner;
    this.isMicrophoneEnabled = false;
    this.isCameraEnabled = false;
    this.isScreenShareEnabled = false;
    this.sourceCalls = [];
    this.rpcCalls = [];
    this.rpcResponse = JSON.stringify({
      version: 1,
      status: "ok",
      accepted_operation_ids: []
    });
    this.rpcError = null;
  }

  async setMicrophoneEnabled(enabled) {
    this.sourceCalls.push(["microphone", enabled]);
    this.isMicrophoneEnabled = enabled;
  }

  async setCameraEnabled(enabled) {
    this.sourceCalls.push(["camera", enabled]);
    this.isCameraEnabled = enabled;
  }

  async setScreenShareEnabled(enabled) {
    this.sourceCalls.push(["screen_share", enabled]);
    this.isScreenShareEnabled = enabled;
  }

  async performRpc(request) {
    this.rpcCalls.push(request);
    if (this.rpcError) throw this.rpcError;
    return this.rpcResponse;
  }
}

class FakeRoom {
  constructor(options) {
    this.options = options;
    this.name = "";
    this.localParticipant = new FakeLocalParticipant("", this);
    this.connectCalls = [];
    this.disconnectCalls = [];
    this.switchCalls = [];
    FakeRoom.instances.push(this);
  }

  async connect(serverUrl, token) {
    this.connectCalls.push([serverUrl, token]);
    const configured = FakeRoom.nextConnect || {};
    if (configured.error) throw configured.error;
    this.name = configured.room || "room-1";
    this.localParticipant.identity = configured.participant || "student-1";
  }

  async disconnect(stopTracks) {
    this.disconnectCalls.push(stopTracks);
    if (FakeRoom.disconnectError) throw FakeRoom.disconnectError;
  }

  async switchActiveDevice(kind, deviceId, exact) {
    this.switchCalls.push([kind, deviceId, exact]);
    if (FakeRoom.switchResult instanceof Error) throw FakeRoom.switchResult;
    return FakeRoom.switchResult === undefined ? true : FakeRoom.switchResult;
  }
}
FakeRoom.instances = [];
FakeRoom.nextConnect = null;
FakeRoom.disconnectError = null;
FakeRoom.switchResult = undefined;

function reset() {
  FakeRoom.instances.length = 0;
  FakeRoom.nextConnect = null;
  FakeRoom.disconnectError = null;
  FakeRoom.switchResult = undefined;
}

function adapter(overrides) {
  return new LiveKitClassroomMediaAdapter(Object.assign({
    livekit: { Room: FakeRoom },
    serverUrl: "wss://media.example.test",
    moderationParticipantIdentity: "moderation-service"
  }, overrides || {}));
}

function credential(overrides) {
  return Object.assign({
    room_id: "room-1",
    participant_id: "student-1",
    token: "short-lived-join-token"
  }, overrides || {});
}

function command(overrides) {
  return Object.assign({
    operation_id: "op-1",
    actor_id: "teacher-1",
    target_id: "student-1",
    action: "publish_permission",
    source: "camera",
    value: false
  }, overrides || {});
}

async function run() {
  reset();

  // Join uses only the server-issued token and never publishes media implicitly.
  const client = adapter();
  const joined = await client.connect(credential(), []);
  const firstRoom = FakeRoom.instances[0];
  check(firstRoom.connectCalls.length === 1, "join did not call LiveKit Room.connect exactly once");
  check(firstRoom.connectCalls[0][0] === "wss://media.example.test", "secure LiveKit URL changed");
  check(firstRoom.connectCalls[0][1] === "short-lived-join-token", "join token did not reach Room.connect");
  check(firstRoom.localParticipant.sourceCalls.length === 0, "join silently enabled camera/microphone");
  check(joined.connected === true && joined.room_id === "room-1", "joined snapshot is wrong");

  await client.setLocalSource("microphone", true);
  await client.setLocalSource("camera", true);
  await client.setLocalSource("screen_share", true);
  check(JSON.stringify(firstRoom.localParticipant.sourceCalls) === JSON.stringify([
    ["microphone", true],
    ["camera", true],
    ["screen_share", true]
  ]), "explicit source actions did not map to LiveKit publication controls");
  const sourceSnapshot = client.snapshot();
  check(sourceSnapshot.microphone_enabled && sourceSnapshot.camera_enabled && sourceSnapshot.screen_share_enabled,
        "published source state was not projected");

  // Moderation is delegated to one trusted server participant. No join token is serialized.
  const commands = [
    command(),
    command({
      operation_id: "op-2",
      action: "soft_mute",
      source: "microphone",
      value: true
    }),
    command({
      operation_id: "op-3",
      target_id: "student-2",
      action: "remove",
      source: null,
      value: true
    })
  ];
  firstRoom.localParticipant.rpcResponse = JSON.stringify({
    version: 1,
    status: "ok",
    accepted_operation_ids: ["op-1", "op-2", "op-3"]
  });
  await client.applyModeration(commands);
  check(firstRoom.localParticipant.rpcCalls.length === 1, "moderation was not one bounded RPC batch");
  const rpc = firstRoom.localParticipant.rpcCalls[0];
  check(rpc.destinationIdentity === "moderation-service", "moderation RPC escaped trusted participant");
  check(rpc.method === DEFAULT_MODERATION_METHOD, "moderation RPC method changed");
  const payload = JSON.parse(rpc.payload);
  check(payload.version === 1 && payload.room_id === "room-1", "moderation protocol identity is wrong");
  check(payload.operations.length === 3, "moderation operation count changed");
  check(!rpc.payload.includes("short-lived-join-token"), "join token leaked into moderation payload");
  check(!rpc.payload.toLowerCase().includes("api_secret"), "desktop payload contains server secret field");

  // Exact acknowledgement is required before canonical controller may publish policy mutation.
  firstRoom.localParticipant.rpcResponse = JSON.stringify({
    version: 1,
    status: "ok",
    accepted_operation_ids: ["op-1"]
  });
  await expectError(() => client.applyModeration([command(), command({ operation_id: "op-2" })]),
                    "acknowledgement is incomplete");

  firstRoom.localParticipant.rpcResponse = JSON.stringify({
    version: 1,
    status: "ok",
    accepted_operation_ids: ["wrong-op"]
  });
  await expectError(() => client.applyModeration([command()]),
                    "does not match request");

  firstRoom.localParticipant.rpcResponse = JSON.stringify({
    version: 1,
    status: "ok",
    accepted_operation_ids: ["op-1"],
    debug: "server internals"
  });
  await expectError(() => client.applyModeration([command()]),
                    "fields are invalid");

  firstRoom.localParticipant.rpcError = new Error("remote server secret: do not expose");
  await expectError(() => client.applyModeration([command()]),
                    "moderation request failed");
  firstRoom.localParticipant.rpcError = null;

  // Device recovery uses LiveKit's active-device switch and republishes only when requested.
  await client.recoverDevice("camera", "camera-device-1", true);
  await client.recoverDevice("microphone", "mic-device-1", false);
  await client.recoverDevice("speaker", "speaker-device-1", false);
  check(JSON.stringify(firstRoom.switchCalls) === JSON.stringify([
    ["videoinput", "camera-device-1", true],
    ["audioinput", "mic-device-1", true],
    ["audiooutput", "speaker-device-1", true]
  ]), "device recovery did not use exact LiveKit device kinds");
  check(firstRoom.localParticipant.sourceCalls[firstRoom.localParticipant.sourceCalls.length - 1][0] === "camera",
        "camera recovery did not republish the requested enabled source");

  // Reconnect creates a fresh Room from a fresh credential and restores only caller-selected sources.
  const beforeReconnectRooms = FakeRoom.instances.length;
  FakeRoom.nextConnect = { room: "room-1", participant: "student-1" };
  const reconnected = await client.reconnect(
    credential({ token: "fresh-reconnect-token" }),
    ["microphone"]
  );
  check(FakeRoom.instances.length === beforeReconnectRooms + 1, "reconnect did not replace the provider Room");
  const secondRoom = FakeRoom.instances[FakeRoom.instances.length - 1];
  check(secondRoom.connectCalls[0][1] === "fresh-reconnect-token", "reconnect reused stale token");
  check(JSON.stringify(secondRoom.localParticipant.sourceCalls) === JSON.stringify([["microphone", true]]),
        "reconnect enabled a source that was not explicitly requested");
  check(reconnected.microphone_enabled && !reconnected.camera_enabled && !reconnected.screen_share_enabled,
        "reconnect snapshot exposes wrong source state");

  // Identity mismatch fails closed and destroys the provider room before publication.
  reset();
  FakeRoom.nextConnect = { room: "room-1", participant: "different-user" };
  const mismatch = adapter();
  await expectError(() => mismatch.connect(credential(), []), "participant identity does not match");
  check(FakeRoom.instances[0].disconnectCalls.length === 1, "identity mismatch left provider room connected");
  check(mismatch.connected === false, "identity mismatch published connected state");

  reset();
  FakeRoom.nextConnect = { room: "other-room", participant: "student-1" };
  const roomMismatch = adapter();
  await expectError(() => roomMismatch.connect(credential(), []), "room identity does not match");
  check(roomMismatch.connected === false, "room mismatch published connected state");

  // Remote endpoints require WSS. Plain WS is accepted only for loopback development.
  let rejectedInsecure = false;
  try {
    adapter({ serverUrl: "ws://media.example.test" });
  } catch (error) {
    rejectedInsecure = error instanceof LiveKitClassroomMediaError;
  }
  check(rejectedInsecure, "non-loopback insecure WebSocket URL was accepted");
  const local = adapter({ serverUrl: "ws://127.0.0.1:7880" });
  check(local.connected === false, "IPv4 loopback development adapter started connected");
  const localIpv6 = adapter({ serverUrl: "ws://[::1]:7880" });
  check(localIpv6.connected === false, "IPv6 loopback development adapter started connected");

  let rejectedCredentialsInUrl = false;
  try {
    adapter({ serverUrl: "wss://user:password@media.example.test" });
  } catch (error) {
    rejectedCredentialsInUrl = error instanceof LiveKitClassroomMediaError;
  }
  check(rejectedCredentialsInUrl, "server URL embedded credentials were accepted");

  // LiveKit RPC method names are bounded to 64 UTF-8 bytes.
  const maxLengthMethod = adapter({ moderationRpcMethod: "m".repeat(64) });
  check(maxLengthMethod.connected === false, "64-byte RPC method was rejected");
  let rejectedLongMethod = false;
  try {
    adapter({ moderationRpcMethod: "m".repeat(65) });
  } catch (error) {
    rejectedLongMethod = error instanceof LiveKitClassroomMediaError &&
      error.message.includes("moderation RPC method is invalid");
  }
  check(rejectedLongMethod, "65-byte RPC method exceeded provider limit without rejection");

  // Fail closed on duplicate operation ids and malformed source/action shapes before RPC.
  reset();
  const validationClient = adapter();
  await validationClient.connect(credential(), []);
  const validationRoom = FakeRoom.instances[0];
  await expectError(
    () => validationClient.applyModeration([command(), command({ target_id: "student-2" })]),
    "operation ids must be unique"
  );
  await expectError(
    () => validationClient.applyModeration([command({ action: "soft_mute", source: "camera" })]),
    "soft mute command is invalid"
  );
  check(validationRoom.localParticipant.rpcCalls.length === 0, "invalid moderation reached provider RPC");

  // LiveKit RPC v1 request/response strings must stay within 15 KiB UTF-8.
  const oversizedCommands = Array.from({ length: 50 }, (_unused, index) => command({
    operation_id: ("op-" + index + "-").padEnd(120, "x"),
    actor_id: ("actor-" + index + "-").padEnd(120, "a"),
    target_id: ("target-" + index + "-").padEnd(120, "t")
  }));
  await expectError(
    () => validationClient.applyModeration(oversizedCommands),
    "moderation request is too large"
  );
  check(validationRoom.localParticipant.rpcCalls.length === 0,
        "oversized moderation request reached provider RPC");

  validationRoom.localParticipant.rpcResponse = "x".repeat(15 * 1024 + 1);
  await expectError(
    () => validationClient.applyModeration([command({ operation_id: "response-limit" })]),
    "moderation acknowledgement is invalid"
  );
  check(validationRoom.localParticipant.rpcCalls.length === 1,
        "oversized provider response did not exercise the RPC response boundary");

  console.log("LiveKit classroom client adapter contract PASS");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
