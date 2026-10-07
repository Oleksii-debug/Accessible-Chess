"use strict";

const fs = require("fs");
const vm = require("vm");

global.window = {};
const source = fs.readFileSync("web/youtube_provider_metadata.js", "utf8");
vm.runInThisContext(source, { filename: "youtube_provider_metadata.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function response(payload, { ok = true } = {}) {
  const text = typeof payload === "string" ? payload : JSON.stringify(payload);
  return {
    ok,
    async text() {
      return text;
    },
  };
}

function fixture(overrides = {}) {
  return {
    items: [
      {
        id: "dQw4w9WgXcQ",
        snippet: {
          title: "Documented metadata fixture",
          channelId: "UC38IQsAvIsxxjztdMZQtwHA",
          channelTitle: "Fixture channel",
          publishedAt: "2009-10-25T06:57:33Z",
          description: "must not cross the adapter",
          thumbnails: { default: { url: "https://example.invalid/ignored.jpg" } },
        },
        contentDetails: {
          duration: "PT3M33S",
          caption: "true",
        },
        status: {
          privacyStatus: "public",
          embeddable: true,
        },
        ...overrides,
      },
    ],
  };
}

async function main() {
  const calls = [];
  const adapter = new window.AccessibleChessYouTubeMetadata.YouTubeProviderMetadataAdapter({
    apiKey: "fixture-api-key",
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return response(fixture());
    },
  });

  const metadata = await adapter.getVideoMetadata("dQw4w9WgXcQ");
  check(calls.length === 1, "metadata adapter made an unexpected request count");
  const request = new URL(calls[0].url);
  check(request.origin === "https://www.googleapis.com", "metadata request escaped the documented API host");
  check(request.pathname === "/youtube/v3/videos", "metadata request escaped videos.list");
  check(request.searchParams.get("id") === "dQw4w9WgXcQ", "metadata request lost video id");
  check(request.searchParams.get("part") === "snippet,contentDetails,status", "metadata request used an unexpected part set");
  check(request.searchParams.has("fields"), "metadata request is not response-bounded");
  check(request.searchParams.get("key") === "fixture-api-key", "metadata request lost API credential");
  check(calls[0].options.method === "GET", "metadata request is not read-only");
  check(calls[0].options.credentials === "omit", "metadata request unexpectedly carries browser credentials");
  check(calls[0].options.redirect === "error", "metadata request permits redirect escape");
  check(calls[0].options.cache === "no-store", "metadata request permits local response caching");

  check(metadata.provider === "youtube_data_api_v3", "provider identity is missing");
  check(metadata.videoId === "dQw4w9WgXcQ", "metadata video id mismatch");
  check(metadata.title === "Documented metadata fixture", "metadata title mismatch");
  check(metadata.duration === "PT3M33S", "metadata duration mismatch");
  check(metadata.captionsAvailable === true, "caption metadata mismatch");
  check(metadata.embeddable === true, "embeddable metadata mismatch");
  check(!("description" in metadata), "unneeded description crossed the bounded metadata surface");
  check(!("thumbnails" in metadata), "unneeded thumbnail URLs crossed the bounded metadata surface");
  check(!("apiKey" in metadata), "API credential crossed the metadata result boundary");

  for (const badId of ["", "short", "dQw4w9WgXcQ?x", " dQw4w9WgXcQ"]) {
    let rejected = false;
    try {
      await adapter.getVideoMetadata(badId);
    } catch (_error) {
      rejected = true;
    }
    check(rejected, `invalid video id was accepted: ${JSON.stringify(badId)}`);
  }

  const malformedCases = [
    {},
    { items: [] },
    { items: [fixture().items[0], fixture().items[0]] },
    fixture({ id: "aaaaaaaaaaa" }),
    fixture({ status: { privacyStatus: "public", embeddable: "yes" } }),
    fixture({ contentDetails: { duration: "PT1M", caption: "maybe" } }),
  ];
  for (const payload of malformedCases) {
    const failing = new window.AccessibleChessYouTubeMetadata.YouTubeProviderMetadataAdapter({
      apiKey: "fixture-api-key",
      fetchImpl: async () => response(payload),
    });
    let rejected = false;
    try {
      await failing.getVideoMetadata("dQw4w9WgXcQ");
    } catch (_error) {
      rejected = true;
    }
    check(rejected, "malformed metadata response was accepted");
  }

  const oversized = new window.AccessibleChessYouTubeMetadata.YouTubeProviderMetadataAdapter({
    apiKey: "fixture-api-key",
    fetchImpl: async () => response("x".repeat(262145)),
  });
  let oversizedRejected = false;
  try {
    await oversized.getVideoMetadata("dQw4w9WgXcQ");
  } catch (_error) {
    oversizedRejected = true;
  }
  check(oversizedRejected, "oversized metadata response was accepted");

  const forbidden = [
    /googlevideo/i,
    /videoplayback/i,
    /get_video_info/i,
    /player_response/i,
    /\.m3u8/i,
    /\.mpd/i,
  ];
  for (const pattern of forbidden) {
    check(!pattern.test(source), `undocumented media surface leaked into metadata adapter: ${pattern}`);
  }

  console.log("youtube_provider_metadata_adapter_test: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
