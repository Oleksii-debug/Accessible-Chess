"use strict";

(function (global) {
  const DEFAULT_MODERATION_METHOD = "accessible-chess.classroom.moderation.v1";
  const MAX_ID_LENGTH = 128;
  const MAX_TOKEN_LENGTH = 8192;
  const MAX_DEVICE_ID_LENGTH = 512;
  const MAX_COMMANDS = 256;
  const MAX_RPC_METHOD_BYTES = 64;
  const MAX_RPC_PAYLOAD_BYTES = 15 * 1024;
  const SOURCE_NAMES = new Set(["microphone", "camera", "screen_share"]);
  const DEVICE_KINDS = new Set(["microphone", "speaker", "camera"]);
  const ACTIONS = new Set(["publish_permission", "soft_mute", "remove"]);

  class LiveKitClassroomMediaError extends Error {
    constructor(message) {
      super(message);
      this.name = "LiveKitClassroomMediaError";
    }
  }

  function utf8ByteLength(value) {
    if (typeof TextEncoder === "function") {
      return new TextEncoder().encode(value).byteLength;
    }
    if (typeof Buffer !== "undefined" && typeof Buffer.byteLength === "function") {
      return Buffer.byteLength(value, "utf8");
    }
    throw new LiveKitClassroomMediaError("UTF-8 byte counter is unavailable");
  }

  function identifier(value, name) {
    if (typeof value !== "string") throw new LiveKitClassroomMediaError(name + " must be text");
    if (!value || value.length > MAX_ID_LENGTH || !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value)) {
      throw new LiveKitClassroomMediaError(name + " is invalid");
    }
    return value;
  }

  function rpcMethod(value) {
    const method = identifier(value, "moderation RPC method");
    if (utf8ByteLength(method) > MAX_RPC_METHOD_BYTES) {
      throw new LiveKitClassroomMediaError("moderation RPC method is invalid");
    }
    return method;
  }

  function secretToken(value) {
    if (typeof value !== "string" || !value || value.length > MAX_TOKEN_LENGTH || /[\s\u007f]/u.test(value)) {
      throw new LiveKitClassroomMediaError("join token is invalid");
    }
    return value;
  }

  function secureServerUrl(value) {
    if (typeof value !== "string" || !value.trim()) {
      throw new LiveKitClassroomMediaError("LiveKit server URL is invalid");
    }
    let parsed;
    try {
      parsed = new URL(value.trim());
    } catch (_error) {
      throw new LiveKitClassroomMediaError("LiveKit server URL is invalid");
    }
    const localHost = parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1" || parsed.hostname === "::1" || parsed.hostname === "[::1]";
    if (parsed.protocol !== "wss:" && !(localHost && parsed.protocol === "ws:")) {
      throw new LiveKitClassroomMediaError("LiveKit server URL must use secure WebSocket transport");
    }
    if (parsed.username || parsed.password || parsed.search || parsed.hash) {
      throw new LiveKitClassroomMediaError("LiveKit server URL must not contain credentials or query data");
    }
    return parsed.toString().replace(/\/$/, "");
  }

  function normalizeSource(value) {
    if (typeof value !== "string" || !SOURCE_NAMES.has(value)) {
      throw new LiveKitClassroomMediaError("media source is invalid");
    }
    return value;
  }

  function normalizeSources(values) {
    if (!Array.isArray(values)) throw new LiveKitClassroomMediaError("enabled sources must be an array");
    const result = [];
    const seen = new Set();
    for (const raw of values) {
      const source = normalizeSource(raw);
      if (seen.has(source)) throw new LiveKitClassroomMediaError("enabled sources contain duplicates");
      seen.add(source);
      result.push(source);
    }
    return result;
  }

  function normalizeCredential(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new LiveKitClassroomMediaError("join credential is invalid");
    }
    const keys = Object.keys(value).sort();
    const allowed = ["participant_id", "room_id", "token"];
    if (keys.length !== allowed.length || !allowed.every((key, index) => keys[index] === key)) {
      throw new LiveKitClassroomMediaError("join credential fields are invalid");
    }
    return {
      room_id: identifier(value.room_id, "room id"),
      participant_id: identifier(value.participant_id, "participant id"),
      token: secretToken(value.token)
    };
  }

  function normalizeCommand(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new LiveKitClassroomMediaError("moderation command is invalid");
    }
    const operationId = identifier(value.operation_id, "operation id");
    const actorId = identifier(value.actor_id, "actor id");
    const targetId = identifier(value.target_id, "target id");
    if (typeof value.action !== "string" || !ACTIONS.has(value.action)) {
      throw new LiveKitClassroomMediaError("moderation action is invalid");
    }

    let source = null;
    let commandValue = value.value;
    if (value.action === "publish_permission") {
      source = normalizeSource(value.source);
      if (typeof commandValue !== "boolean") throw new LiveKitClassroomMediaError("publish permission value is invalid");
    } else if (value.action === "soft_mute") {
      if (value.source !== "microphone" || typeof commandValue !== "boolean") {
        throw new LiveKitClassroomMediaError("soft mute command is invalid");
      }
      source = "microphone";
    } else {
      if (value.source !== null && value.source !== undefined) {
        throw new LiveKitClassroomMediaError("remove command must not carry a source");
      }
      if (typeof commandValue !== "boolean") throw new LiveKitClassroomMediaError("remove block flag is invalid");
    }

    return {
      operation_id: operationId,
      actor_id: actorId,
      target_id: targetId,
      action: value.action,
      source,
      value: commandValue
    };
  }

  function exactAck(raw, operationIds) {
    if (typeof raw !== "string" || utf8ByteLength(raw) > MAX_RPC_PAYLOAD_BYTES) {
      throw new LiveKitClassroomMediaError("moderation acknowledgement is invalid");
    }
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (_error) {
      throw new LiveKitClassroomMediaError("moderation acknowledgement is invalid");
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new LiveKitClassroomMediaError("moderation acknowledgement is invalid");
    }
    const keys = Object.keys(parsed).sort();
    const expectedKeys = ["accepted_operation_ids", "status", "version"];
    if (keys.length !== expectedKeys.length || !expectedKeys.every((key, index) => keys[index] === key)) {
      throw new LiveKitClassroomMediaError("moderation acknowledgement fields are invalid");
    }
    if (parsed.version !== 1 || parsed.status !== "ok" || !Array.isArray(parsed.accepted_operation_ids)) {
      throw new LiveKitClassroomMediaError("moderation acknowledgement is invalid");
    }
    if (parsed.accepted_operation_ids.length !== operationIds.length) {
      throw new LiveKitClassroomMediaError("moderation acknowledgement is incomplete");
    }
    for (let index = 0; index < operationIds.length; index += 1) {
      if (parsed.accepted_operation_ids[index] !== operationIds[index]) {
        throw new LiveKitClassroomMediaError("moderation acknowledgement does not match request");
      }
    }
  }

  class LiveKitClassroomMediaAdapter {
    constructor(options) {
      if (!options || typeof options !== "object") {
        throw new LiveKitClassroomMediaError("LiveKit adapter options are required");
      }
      if (!options.livekit || typeof options.livekit.Room !== "function") {
        throw new LiveKitClassroomMediaError("LiveKit Room constructor is unavailable");
      }
      this._livekit = options.livekit;
      this._serverUrl = secureServerUrl(options.serverUrl);
      this._moderationParticipantIdentity = identifier(
        options.moderationParticipantIdentity,
        "moderation participant identity"
      );
      this._moderationRpcMethod = rpcMethod(
        options.moderationRpcMethod || DEFAULT_MODERATION_METHOD
      );
      this._roomOptions = options.roomOptions && typeof options.roomOptions === "object"
        ? Object.freeze(Object.assign({}, options.roomOptions))
        : Object.freeze({});
      this._room = null;
      this._cleanupRoom = null;
      this._roomId = null;
      this._participantId = null;
    }

    get connected() {
      return this._room !== null;
    }

    get roomId() {
      return this._roomId;
    }

    get participantId() {
      return this._participantId;
    }

    async connect(credentialValue, enabledSourcesValue) {
      if (this._room !== null) throw new LiveKitClassroomMediaError("media session is already connected");
      if (this._cleanupRoom !== null) throw new LiveKitClassroomMediaError("media session cleanup is required");
      const credential = normalizeCredential(credentialValue);
      const enabledSources = normalizeSources(enabledSourcesValue || []);
      const room = new this._livekit.Room(this._roomOptions);
      try {
        await room.connect(this._serverUrl, credential.token);
        if (!room.localParticipant || room.localParticipant.identity !== credential.participant_id) {
          throw new LiveKitClassroomMediaError("LiveKit participant identity does not match join credential");
        }
        if (room.localParticipant.identity === this._moderationParticipantIdentity) {
          throw new LiveKitClassroomMediaError("moderation participant identity must be remote");
        }
        if (typeof room.name !== "string" || room.name !== credential.room_id) {
          throw new LiveKitClassroomMediaError("LiveKit room identity does not match join credential");
        }
        this._room = room;
        this._roomId = credential.room_id;
        this._participantId = credential.participant_id;
        for (const source of enabledSources) {
          await this._setLocalSourceOnRoom(room, source, true);
        }
        return this.snapshot();
      } catch (error) {
        try {
          await room.disconnect(true);
        } catch (_disconnectError) {
          // If validation already published this Room as the active session,
          // retain it so the caller can see any still-enabled media and retry
          // disconnect. Otherwise retain a cleanup-only handle without
          // publishing an untrusted room/participant identity as connected.
          if (this._room !== room) {
            this._cleanupRoom = room;
          }
          throw new LiveKitClassroomMediaError(
            "LiveKit room connection failed; media cleanup is still required"
          );
        }
        if (this._room === room) {
          this._room = null;
          this._roomId = null;
          this._participantId = null;
        }
        if (error instanceof LiveKitClassroomMediaError) throw error;
        throw new LiveKitClassroomMediaError("LiveKit room connection failed");
      }
    }

    async reconnect(credentialValue, enabledSourcesValue) {
      if (this._room !== null) {
        await this.disconnect();
      }
      return this.connect(credentialValue, enabledSourcesValue);
    }

    async disconnect() {
      const room = this._room !== null ? this._room : this._cleanupRoom;
      if (room === null) return this.snapshot();
      try {
        await room.disconnect(true);
      } catch (_error) {
        // Do not report a false disconnected state or lose the only cleanup
        // handle when the provider cannot confirm teardown.
        throw new LiveKitClassroomMediaError("LiveKit room disconnect failed");
      }
      if (this._room === room) {
        this._room = null;
        this._roomId = null;
        this._participantId = null;
      }
      if (this._cleanupRoom === room) {
        this._cleanupRoom = null;
      }
      return this.snapshot();
    }

    async setLocalSource(sourceValue, enabled) {
      if (typeof enabled !== "boolean") throw new LiveKitClassroomMediaError("media enabled flag is invalid");
      const source = normalizeSource(sourceValue);
      const room = this._requireRoom();
      try {
        await this._setLocalSourceOnRoom(room, source, enabled);
      } catch (_error) {
        throw new LiveKitClassroomMediaError("LiveKit local media change failed");
      }
      return this.snapshot();
    }

    async recoverDevice(kindValue, deviceIdValue, republishEnabled) {
      if (typeof kindValue !== "string" || !DEVICE_KINDS.has(kindValue)) {
        throw new LiveKitClassroomMediaError("media device kind is invalid");
      }
      if (typeof deviceIdValue !== "string" || !deviceIdValue || deviceIdValue.length > MAX_DEVICE_ID_LENGTH ||
          /[\u0000-\u001f\u007f]/.test(deviceIdValue)) {
        throw new LiveKitClassroomMediaError("media device id is invalid");
      }
      if (typeof republishEnabled !== "boolean") {
        throw new LiveKitClassroomMediaError("device republish flag is invalid");
      }
      const room = this._requireRoom();
      const livekitKind = kindValue === "microphone" ? "audioinput" : kindValue === "speaker" ? "audiooutput" : "videoinput";
      try {
        const switched = await room.switchActiveDevice(livekitKind, deviceIdValue, true);
        if (switched !== true) throw new Error("device switch was rejected");
        if (republishEnabled && kindValue === "microphone") {
          await room.localParticipant.setMicrophoneEnabled(true);
        } else if (republishEnabled && kindValue === "camera") {
          await room.localParticipant.setCameraEnabled(true);
        }
      } catch (_error) {
        throw new LiveKitClassroomMediaError("LiveKit device recovery failed");
      }
      return this.snapshot();
    }

    async applyModeration(commandValues) {
      if (!Array.isArray(commandValues) || commandValues.length > MAX_COMMANDS) {
        throw new LiveKitClassroomMediaError("moderation command batch is invalid");
      }
      if (commandValues.length === 0) return;
      const room = this._requireRoom();
      const commands = commandValues.map(normalizeCommand);
      const operationIds = commands.map((command) => command.operation_id);
      if (new Set(operationIds).size !== operationIds.length) {
        throw new LiveKitClassroomMediaError("moderation operation ids must be unique");
      }
      const payload = JSON.stringify({
        version: 1,
        room_id: this._roomId,
        operations: commands
      });
      if (utf8ByteLength(payload) > MAX_RPC_PAYLOAD_BYTES) {
        throw new LiveKitClassroomMediaError("moderation request is too large");
      }

      let response;
      try {
        response = await room.localParticipant.performRpc({
          destinationIdentity: this._moderationParticipantIdentity,
          method: this._moderationRpcMethod,
          payload
        });
      } catch (_error) {
        throw new LiveKitClassroomMediaError("LiveKit moderation request failed");
      }
      exactAck(response, operationIds);
    }

    snapshot() {
      if (this._room === null) {
        return Object.freeze({
          connected: false,
          cleanup_required: this._cleanupRoom !== null,
          room_id: null,
          participant_id: null,
          microphone_enabled: false,
          camera_enabled: false,
          screen_share_enabled: false
        });
      }
      const local = this._room.localParticipant;
      return Object.freeze({
        connected: true,
        cleanup_required: false,
        room_id: this._roomId,
        participant_id: this._participantId,
        microphone_enabled: Boolean(local.isMicrophoneEnabled),
        camera_enabled: Boolean(local.isCameraEnabled),
        screen_share_enabled: Boolean(local.isScreenShareEnabled)
      });
    }

    _requireRoom() {
      if (this._room === null || !this._room.localParticipant) {
        throw new LiveKitClassroomMediaError("media session is not connected");
      }
      return this._room;
    }

    async _setLocalSourceOnRoom(room, source, enabled) {
      if (source === "microphone") {
        await room.localParticipant.setMicrophoneEnabled(enabled);
      } else if (source === "camera") {
        await room.localParticipant.setCameraEnabled(enabled);
      } else {
        await room.localParticipant.setScreenShareEnabled(enabled);
      }
    }
  }

  const exported = Object.freeze({
    LiveKitClassroomMediaAdapter,
    LiveKitClassroomMediaError,
    DEFAULT_MODERATION_METHOD
  });
  global.AccessibleChessLiveKitMedia = exported;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = exported;
  }
})(typeof window !== "undefined" ? window : globalThis);
