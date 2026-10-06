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
    if (FakeRoom.sourceError === "microphone") throw new Error("microphone publication failed");
    this.isMicrophoneEnabled = enabled;
  }

  async setCameraEnabled(enabled) {
    this.sourceCalls.push(["camera", enabled]);
    if (FakeRoom.sourceError === "camera") throw new Error("camera publication failed");
    this.isCameraEnabled = enabled;
  }

  async setScreenShareEnabled(enabled) {
    this.sourceCalls.push(["screen_share", enabled]);
    if (FakeRoom.sourceError === "screen_share") throw new Error("screen-share publication failed");
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
FakeRoom.sourceError = null;

function reset() {
  FakeRoom.instances.length = 0;
  FakeRoom.nextConnect = null;
  FakeRoom.disconnectError = null;
  FakeRoom.switchResult = undefined;
  FakeRoom.sourceError = null;
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

  // Failed disconnect must retain the active Room and visible media state so
  // cleanup can be retried instead of falsely reporting that capture stopped.
  reset();
  const disconnectClient = adapter();
  await disconnectClient.connect(credential(), ["microphone"]);
  const disconnectRoom = FakeRoom.instances[0];
  FakeRoom.disconnectError = new Error("provider teardown failed");
  await expectError(() => disconnectClient.disconnect(), "room disconnect failed");
  const failedDisconnectSnapshot = disconnectClient.snapshot();
  check(disconnectClient.connected === true, "failed disconnect lost the active Room handle");
  check(failedDisconnectSnapshot.microphone_enabled === true,
        "failed disconnect hid a microphone that may still be published");
  check(failedDisconnectSnapshot.cleanup_required === false,
        "validated active Room was mislabeled as cleanup-only");
  check(disconnectRoom.disconnectCalls.length === 1, "failed disconnect was not attempted");
  FakeRoom.disconnectError = null;
  const disconnectedSnapshot = await disconnectClient.disconnect();
  check(disconnectedSnapshot.connected === false && disconnectedSnapshot.cleanup_required === false,
        "disconnect retry did not clear the provider Room");

  // If media enablement fails and rollback teardown also fails, retain the
  // validated Room rather than losing authority over already-enabled sources.
  reset();
  FakeRoom.sourceError = "camera";
  FakeRoom.disconnectError = new Error("rollback teardown failed");
  const rollbackClient = adapter();
  await expectError(
    () => rollbackClient.connect(credential(), ["microphone", "camera"]),
    "media cleanup is still required"
  );
  const rollbackSnapshot = rollbackClient.snapshot();
  check(rollbackSnapshot.connected === true,
        "failed connection rollback lost a validated provider Room");
  check(rollbackSnapshot.microphone_enabled === true,
        "failed connection rollback hid already-enabled microphone state");
  FakeRoom.sourceError = null;
  FakeRoom.disconnectError = null;
  await rollbackClient.disconnect();
  check(rollbackClient.connected === false, "rollback cleanup retry did not disconnect");

  // Identity mismatch fails closed and destroys the provider room before publication.
  reset();
  FakeRoom.nextConnect = { room: "room-1", participant: "different-user" };
  const mismatch = adapter();
  await expectError(() => mismatch.connect(credential(), []), "participant identity does not match");
  check(FakeRoom.instances[0].disconnectCalls.length === 1, "identity mismatch left provider room connected");
  check(mismatch.connected === false, "identity mismatch published connected state");
  check(mismatch.snapshot().cleanup_required === false,
        "successful identity-mismatch cleanup left stale cleanup state");

  // If an untrusted identity cannot be disconnected, keep only a cleanup handle:
  // do not publish it as connected, and do not permit another join until cleanup succeeds.
  reset();
  FakeRoom.nextConnect = { room: "room-1", participant: "different-user" };
  FakeRoom.disconnectError = new Error("identity cleanup failed");
  const cleanupOnly = adapter();
  await expectError(
    () => cleanupOnly.connect(credential(), []),
    "media cleanup is still required"
  );
  const cleanupOnlySnapshot = cleanupOnly.snapshot();
  check(cleanupOnlySnapshot.connected === false && cleanupOnlySnapshot.cleanup_required === true,
        "untrusted failed cleanup did not remain explicitly recoverable");
  await expectError(() => cleanupOnly.connect(credential(), []), "media session cleanup is required");
  FakeRoom.disconnectError = null;
  const cleanedSnapshot = await cleanupOnly.disconnect();
  check(cleanedSnapshot.connected === false && cleanedSnapshot.cleanup_required === false,
        "cleanup-only Room was not released on retry");

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

  // Canonical opaque identifiers are exact: surrounding whitespace is invalid,
  // not silently normalized into a different room or participant identity.
  reset();
  const invalidIdentityClient = adapter();
  await expectError(
    () => invalidIdentityClient.connect(credential({ room_id: " room-1" }), []),
    "room id is invalid"
  );
  check(FakeRoom.instances.length === 0,
        "invalid room identity reached the provider Room constructor");

  // Join credentials match the Python authority: no whitespace is accepted in
  // the short-lived secret token, so malformed secrets never reach LiveKit.
  reset();
  const invalidTokenClient = adapter();
  await expectError(
    () => invalidTokenClient.connect(credential({ token: "token with space" }), []),
    "join token is invalid"
  );
  check(FakeRoom.instances.length === 0,
        "whitespace-bearing join token reached the provider Room constructor");

  // The designated moderation participant is a remote trusted service boundary,
  // never the same classroom client that is making the request.
  reset();
  const selfModerationClient = adapter({ moderationParticipantIdentity: "student-1" });
  await expectError(
    () => selfModerationClient.connect(credential(), []),
    "moderation participant identity must be remote"
  );
  check(FakeRoom.instances.length === 1 &&
        FakeRoom.instances[0].disconnectCalls.length === 1,
        "self-moderation identity rejection did not tear down the provider Room");
  check(selfModerationClient.connected === false &&
        selfModerationClient.snapshot().cleanup_required === false,
        "self-moderation identity rejection published or retained stale state");

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
