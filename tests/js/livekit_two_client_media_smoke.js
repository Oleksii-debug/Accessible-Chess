"use strict";

/*
 * Real-provider Issue #26 acceptance smoke.
 *
 * This intentionally exercises the shipped browser adapter against a real
 * pinned LiveKit server. Tokens enter the browser only as evaluate() arguments;
 * they are never placed in URLs, DOM text, console output, or fixture source.
 */

const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("playwright");

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function args() {
  const values = {};
  for (let index = 2; index < process.argv.length; index += 2) {
    const key = process.argv[index];
    const value = process.argv[index + 1];
    if (!key || !key.startsWith("--") || value === undefined) {
      throw new Error("smoke arguments must be --name value pairs");
    }
    values[key.slice(2)] = value;
  }
  for (const required of ["credentials", "sdk", "adapter"]) {
    if (!values[required]) throw new Error("missing --" + required);
  }
  return values;
}

function exactCredentialPayload(file) {
  const value = JSON.parse(fs.readFileSync(file, "utf8"));
  check(value && typeof value === "object" && !Array.isArray(value), "credential fixture root is invalid");
  check(value.schema_version === 1, "credential fixture schema is invalid");
  check(typeof value.room_id === "string" && value.room_id.length > 0, "room id is invalid");
  for (const name of ["publisher", "subscriber"]) {
    const entry = value[name];
    check(entry && typeof entry === "object" && !Array.isArray(entry), name + " credential is invalid");
    check(typeof entry.participant_id === "string" && entry.participant_id.length > 0,
      name + " participant id is invalid");
    check(typeof entry.token === "string" && entry.token.split(".").length === 3,
      name + " token is invalid");
  }
  check(value.publisher.participant_id !== value.subscriber.participant_id,
    "smoke participants must have distinct identities");
  return value;
}

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return server.address().port;
}

async function closeServer(server) {
  await new Promise((resolve) => server.close(resolve));
}

async function main() {
  const input = args();
  const credentials = exactCredentialPayload(input.credentials);
  const sdk = fs.readFileSync(input.sdk, "utf8");
  const adapter = fs.readFileSync(input.adapter, "utf8");
  check(sdk.includes("LivekitClient") && sdk.includes("Room"), "pinned SDK markers are absent");
  check(adapter.includes("AccessibleChessLiveKitMedia"), "project adapter marker is absent");

  const server = http.createServer((request, response) => {
    if (request.url === "/livekit-client.umd.js") {
      response.writeHead(200, { "content-type": "application/javascript; charset=utf-8" });
      response.end(sdk);
      return;
    }
    if (request.url === "/livekit_classroom_media.js") {
      response.writeHead(200, { "content-type": "application/javascript; charset=utf-8" });
      response.end(adapter);
      return;
    }
    if (request.url === "/" || request.url === "/index.html") {
      response.writeHead(200, {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
      });
      response.end([
        "<!doctype html><html><head><meta charset=\"utf-8\">",
        "<title>Accessible Chess LiveKit smoke</title></head><body>",
        "<p id=\"status\">smoke host</p>",
        "<script src=\"/livekit-client.umd.js\"></script>",
        "<script src=\"/livekit_classroom_media.js\"></script>",
        "</body></html>",
      ].join(""));
      return;
    }
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    response.end("not found");
  });

  const port = await listen(server);
  const origin = "http://127.0.0.1:" + port;
  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      args: [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        "--autoplay-policy=no-user-gesture-required",
      ],
    });
    const context = await browser.newContext();
    await context.grantPermissions(["camera", "microphone"], { origin });

    const publisher = await context.newPage();
    const subscriber = await context.newPage();
    await Promise.all([
      publisher.goto(origin, { waitUntil: "load" }),
      subscriber.goto(origin, { waitUntil: "load" }),
    ]);

    for (const page of [publisher, subscriber]) {
      await page.waitForFunction(() =>
        Boolean(window.LivekitClient && window.AccessibleChessLiveKitMedia)
      );
    }

    const serverUrl = "ws://127.0.0.1:7880";
    const moderationIdentity = "moderation-service";

    const connect = async (page, entry) => page.evaluate(
      async ({ serverUrl, moderationIdentity, roomId, participantId, token }) => {
        const api = window.AccessibleChessLiveKitMedia;
        window.__acAdapter = new api.LiveKitClassroomMediaAdapter({
          livekit: window.LivekitClient,
          serverUrl,
          moderationParticipantIdentity: moderationIdentity,
        });
        return window.__acAdapter.connect({
          room_id: roomId,
          participant_id: participantId,
          token,
        }, []);
      },
      {
        serverUrl,
        moderationIdentity,
        roomId: credentials.room_id,
        participantId: entry.participant_id,
        token: entry.token,
      }
    );

    const publisherJoin = await connect(publisher, credentials.publisher);
    const subscriberJoin = await connect(subscriber, credentials.subscriber);
    check(publisherJoin.connected === true && subscriberJoin.connected === true,
      "both real provider participants must connect");
    check(publisherJoin.room_id === credentials.room_id &&
          subscriberJoin.room_id === credentials.room_id,
      "real provider room identity drifted");
    check(!publisherJoin.microphone_enabled && !publisherJoin.camera_enabled,
      "join silently published publisher media");
    check(!subscriberJoin.microphone_enabled && !subscriberJoin.camera_enabled,
      "join silently published subscriber media");

    await subscriber.evaluate(() => {
      const room = window.__acAdapter && window.__acAdapter._room;
      if (!room) throw new Error("subscriber LiveKit room handle is unavailable");
      window.__acSubscriptions = [];
      room.on(window.LivekitClient.RoomEvent.TrackSubscribed, (track, publication, participant) => {
        const mediaTrack = track && track.mediaStreamTrack;
        window.__acSubscriptions.push({
          kind: String((track && track.kind) || ""),
          source: String((publication && publication.source) || ""),
          participant_id: String((participant && participant.identity) || ""),
          ready_state: mediaTrack ? String(mediaTrack.readyState || "") : "",
        });
      });
    });

    await publisher.evaluate(async () => {
      await window.__acAdapter.setLocalSource("microphone", true);
      await window.__acAdapter.setLocalSource("camera", true);
    });

    await subscriber.waitForFunction(
      ({ publisherId }) => {
        const values = window.__acSubscriptions || [];
        const sources = new Set(
          values
            .filter((item) => item.participant_id === publisherId)
            .map((item) => item.source)
        );
        return sources.has("microphone") && sources.has("camera");
      },
      { publisherId: credentials.publisher.participant_id },
      { timeout: 30000 }
    );

    const publisherSnapshot = await publisher.evaluate(() => window.__acAdapter.snapshot());
    check(publisherSnapshot.connected === true, "publisher disconnected during media publication");
    check(publisherSnapshot.microphone_enabled === true, "microphone publication was not enabled");
    check(publisherSnapshot.camera_enabled === true, "camera publication was not enabled");
    check(publisherSnapshot.screen_share_enabled === false, "screen share was enabled unexpectedly");

    const received = await subscriber.evaluate(() => window.__acSubscriptions.slice());
    const publisherTracks = received.filter(
      (item) => item.participant_id === credentials.publisher.participant_id
    );
    const bySource = new Map(publisherTracks.map((item) => [item.source, item]));
    for (const source of ["microphone", "camera"]) {
      const event = bySource.get(source);
      check(event, "subscriber did not receive " + source + " subscription");
      check(event.ready_state === "live", source + " remote media track is not live");
    }

    const subscriberSnapshot = await subscriber.evaluate(() => window.__acAdapter.snapshot());
    check(subscriberSnapshot.connected === true, "subscriber disconnected during media publication");
    check(!subscriberSnapshot.microphone_enabled && !subscriberSnapshot.camera_enabled,
      "subscriber published media without an explicit action");

    await Promise.all([
      publisher.evaluate(() => window.__acAdapter.disconnect()),
      subscriber.evaluate(() => window.__acAdapter.disconnect()),
    ]);

    console.log(
      "LIVEKIT_TWO_CLIENT_MEDIA_SMOKE=PASS " +
      "room=" + credentials.room_id +
      " publisher=" + credentials.publisher.participant_id +
      " subscriber=" + credentials.subscriber.participant_id +
      " tracks=microphone,camera"
    );
  } finally {
    if (browser) await browser.close();
    await closeServer(server);
  }
}

main().catch((error) => {
  console.error("LIVEKIT_TWO_CLIENT_MEDIA_SMOKE=FAIL", error && error.message ? error.message : String(error));
  process.exitCode = 1;
});
