"use strict";

(function (global) {
  const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
  const ENDPOINT = "https://www.googleapis.com/youtube/v3/videos";
  const MAX_RESPONSE_BYTES = 262144;
  const MAX_TEXT = 4096;
  const PARTS = "snippet,contentDetails,status";
  const FIELDS = "items(id,snippet(title,channelId,channelTitle,publishedAt),contentDetails(duration,caption),status(privacyStatus,embeddable))";

  function exactText(value, name, limit = MAX_TEXT) {
    if (
      typeof value !== "string" ||
      !value ||
      value !== value.trim() ||
      value.length > limit ||
      /[\u0000-\u001f\u007f]/.test(value)
    ) {
      throw new Error(`invalid ${name}`);
    }
    return value;
  }

  function exactVideoId(value) {
    const id = exactText(value, "YouTube video id", 64);
    if (!VIDEO_ID.test(id)) throw new Error("invalid YouTube video id");
    return id;
  }

  function boundedOptionalText(value, name, limit = MAX_TEXT) {
    if (value === undefined || value === null || value === "") return null;
    return exactText(value, name, limit);
  }

  function parseMetadata(payload, expectedVideoId) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error("invalid YouTube metadata response");
    }
    if (!Array.isArray(payload.items) || payload.items.length !== 1) {
      throw new Error("YouTube metadata response must contain exactly one video");
    }
    const item = payload.items[0];
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new Error("invalid YouTube video metadata");
    }
    if (exactVideoId(item.id) !== expectedVideoId) {
      throw new Error("YouTube metadata video id mismatch");
    }
    const snippet = item.snippet;
    const contentDetails = item.contentDetails;
    const status = item.status;
    if (
      !snippet || typeof snippet !== "object" || Array.isArray(snippet) ||
      !contentDetails || typeof contentDetails !== "object" || Array.isArray(contentDetails) ||
      !status || typeof status !== "object" || Array.isArray(status)
    ) {
      throw new Error("YouTube metadata fields are incomplete");
    }
    if (typeof status.embeddable !== "boolean") {
      throw new Error("invalid YouTube embeddable metadata");
    }
    const privacyStatus = exactText(status.privacyStatus, "YouTube privacy status", 32);
    if (!["public", "unlisted", "private"].includes(privacyStatus)) {
      throw new Error("unsupported YouTube privacy status");
    }
    const caption = exactText(contentDetails.caption, "YouTube caption status", 16);
    if (!["true", "false"].includes(caption)) {
      throw new Error("invalid YouTube caption status");
    }

    return Object.freeze({
      provider: "youtube_data_api_v3",
      videoId: expectedVideoId,
      title: exactText(snippet.title, "YouTube title", 512),
      channelId: exactText(snippet.channelId, "YouTube channel id", 128),
      channelTitle: exactText(snippet.channelTitle, "YouTube channel title", 512),
      publishedAt: boundedOptionalText(snippet.publishedAt, "YouTube publication time", 64),
      duration: exactText(contentDetails.duration, "YouTube duration", 64),
      captionsAvailable: caption === "true",
      privacyStatus,
      embeddable: status.embeddable,
    });
  }

  class YouTubeProviderMetadataAdapter {
    constructor({ fetchImpl, apiKey }) {
      if (typeof fetchImpl !== "function") {
        throw new Error("documented metadata fetch implementation is required");
      }
      this._fetch = fetchImpl;
      this._apiKey = exactText(apiKey, "YouTube Data API key", 512);
      Object.freeze(this);
    }

    async getVideoMetadata(videoId) {
      const id = exactVideoId(videoId);
      const url = new URL(ENDPOINT);
      url.searchParams.set("part", PARTS);
      url.searchParams.set("id", id);
      url.searchParams.set("fields", FIELDS);
      url.searchParams.set("key", this._apiKey);

      const response = await this._fetch(url.toString(), {
        method: "GET",
        credentials: "omit",
        redirect: "error",
        cache: "no-store",
        headers: Object.freeze({ Accept: "application/json" }),
      });
      if (!response || typeof response !== "object") {
        throw new Error("invalid YouTube metadata HTTP response");
      }
      if (response.ok !== true) {
        throw new Error("YouTube metadata request failed");
      }
      if (typeof response.text !== "function") {
        throw new Error("YouTube metadata response body is unavailable");
      }
      const text = await response.text();
      if (typeof text !== "string") {
        throw new Error("invalid YouTube metadata response body");
      }
      const byteLength =
        typeof TextEncoder === "function"
          ? new TextEncoder().encode(text).length
          : text.length;
      if (byteLength === 0 || byteLength > MAX_RESPONSE_BYTES) {
        throw new Error("YouTube metadata response exceeds safety bounds");
      }
      let payload;
      try {
        payload = JSON.parse(text);
      } catch (_error) {
        throw new Error("YouTube metadata response is not valid JSON");
      }
      return parseMetadata(payload, id);
    }
  }

  global.AccessibleChessYouTubeMetadata = Object.freeze({
    YouTubeProviderMetadataAdapter,
    endpoint: ENDPOINT,
  });
})(typeof window !== "undefined" ? window : globalThis);
