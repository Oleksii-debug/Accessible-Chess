"use strict";

const fs = require("fs");
const vm = require("vm");

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this.id = "";
    this.textContent = "";
    this.disabled = false;
    this.value = "";
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  insertBefore(child, reference) {
    child.parentNode = this;
    const index = this.children.indexOf(reference);
    if (index < 0) this.children.push(child);
    else this.children.splice(index, 0, child);
    return child;
  }

  replaceChildren(...children) {
    this.children = [];
    for (const child of children) this.appendChild(child);
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  removeAttribute(name) {
    delete this.attributes[String(name)];
  }

  getAttribute(name) {
    const key = String(name);
    return Object.prototype.hasOwnProperty.call(this.attributes, key)
      ? this.attributes[key]
      : null;
  }

  addEventListener(name, listener) {
    this.listeners[String(name)] = listener;
  }

  focus() {
    document.activeElement = this;
  }

  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }

  querySelector(selector) {
    if (!String(selector).startsWith("#")) return null;
    const id = String(selector).slice(1);
    return this.descendants().find((item) => item.id === id) || null;
  }
}

const root = new FakeElement("body");
const workspace = new FakeElement("main");
workspace.id = "v2-workspace";
const originalMain = new FakeElement("main");
originalMain.id = "main-content";
root.appendChild(workspace);
root.appendChild(originalMain);

const document = {
  activeElement: null,
  documentElement: { lang: "en" },
  head: new FakeElement("head"),
  createElement: (tagName) => new FakeElement(tagName),
  getElementById(id) {
    if (root.id === id) return root;
    return root.descendants().find((item) => item.id === id) || null;
  },
};

global.document = document;

const opened = [];
const synchronized = [];
const hostCommands = [];
const providerCommands = [];
const renders = [];

function playerState(overrides = {}) {
  return {
    ok: false,
    revision: null,
    positionMs: null,
    durationMs: null,
    positionText: "—",
    regionLabel: "Recorded chess media player",
    heading: "Recorded chess media",
    seekLabel: "Recorded media position",
    backLabel: "Back 10 seconds",
    forwardLabel: "Forward 10 seconds",
    restoreLabel: "Restore synchronized chess position",
    cancelLabel: "Cancel media preprocessing",
    progressLabel: "Preprocessing progress",
    playbackState: "unstarted",
    qualification: "unavailable",
    statusText: "Recorded media synchronization is unavailable.",
    restoreEnabled: false,
    playAction: "play",
    playLabel: "Play recorded media",
    seekEnabled: false,
    cancelEnabled: false,
    preprocessStatus: "unavailable",
    preprocessCompleted: 0,
    preprocessTotal: 0,
    progressText: "Media preprocessing status is unavailable.",
    announcement: "",
    focusTarget: "recorded-media-status",
    ...overrides,
  };
}

function envelope(providerKind, overrides = {}) {
  return {
    ok: true,
    providerKind,
    sourceTitle: providerKind === "youtube" ? "YouTube fixture" : "Local fixture",
    revision: 1,
    player: playerState(),
    ...overrides,
  };
}

const windowObject = {
  document,
  location: { origin: "http://127.0.0.1:8765" },
  setTimeout,
  YT: { Player: function Player() {} },
  pywebview: {
    api: {
      media_workflow_open_pasted: async (source) => {
        opened.push(["pasted", source]);
        return envelope("youtube");
      },
      media_workflow_open_local: async () => {
        opened.push(["local", null]);
        return envelope("host", {
          player: playerState({
            ok: true,
            positionMs: 20500,
            durationMs: 60000,
            positionText: "00:20",
            playbackState: "paused",
            qualification: "confirmed",
            restoreEnabled: true,
            seekEnabled: true,
            focusTarget: "recorded-media-restore",
          }),
        });
      },
      media_workflow_sync_playback: async (sourceId, positionMs, durationMs, playbackState) => {
        synchronized.push([sourceId, positionMs, durationMs, playbackState]);
        return envelope("youtube", {
          player: playerState({
            ok: true,
            positionMs,
            durationMs,
            positionText: "00:20",
            playbackState,
            qualification: "confirmed",
            restoreEnabled: true,
            seekEnabled: true,
            focusTarget: "recorded-media-restore",
          }),
        });
      },
      media_workflow_command: async (action, positionMs) => {
        hostCommands.push([action, positionMs]);
        const kind = windowObject.AccessibleChessSection20MediaWorkflow.currentProviderKind();
        return envelope(kind || "host", {
          player: playerState({
            ok: true,
            positionMs: 20500,
            durationMs: 60000,
            positionText: "00:20",
            playbackState: "paused",
            qualification: "confirmed",
            restoreEnabled: true,
            seekEnabled: true,
            announcement: action === "restore" ? "Restored media position." : "",
            focusTarget: "recorded-media-restore",
          }),
        });
      },
    },
  },
};

windowObject.AccessibleChessRecordedMediaPlayer = {
  render(rootNode, state, runner, focusAfterRender) {
    renders.push({ state, focusAfterRender });
    rootNode.__runner = runner;
    rootNode.__state = state;
    return state;
  },
};

class FakeYouTubeAdapter {
  constructor({ source, onSnapshot }) {
    this.source = source;
    this.onSnapshot = onSnapshot;
    this.positionMs = 20500;
    this.playbackState = "paused";
    setImmediate(() => {
      this.onSnapshot(this.snapshot());
    });
  }

  snapshot() {
    return {
      sourceId: "youtube:dQw4w9WgXcQ",
      positionMs: this.positionMs,
      durationMs: 60000,
      playbackState: this.playbackState,
    };
  }

  play() {
    providerCommands.push(["play", null]);
    this.playbackState = "playing";
  }

  pause() {
    providerCommands.push(["pause", null]);
    this.playbackState = "paused";
  }

  seek(positionMs) {
    providerCommands.push(["seek", positionMs]);
    this.positionMs = positionMs;
  }

  refresh() {
    this.onSnapshot(this.snapshot());
    return this.snapshot();
  }

  destroy() {
    providerCommands.push(["destroy", null]);
    return true;
  }
}

windowObject.AccessibleChessYouTubeIframePlayback = {
  YouTubeIframePlaybackAdapter: FakeYouTubeAdapter,
};

global.window = windowObject;

function check(condition, message) {
  if (!condition) throw new Error(message);
}

async function settle() {
  await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
  await Promise.resolve();
}

async function main() {
  vm.runInThisContext(
    fs.readFileSync("web/version2_media_user_workflow.js", "utf8"),
    { filename: "version2_media_user_workflow.js" },
  );

  const region = document.getElementById("section20-media-workflow");
  const input = document.getElementById("section20-media-source");
  const pastedButton = document.getElementById("section20-media-open-pasted");
  const localButton = document.getElementById("section20-media-open-local");
  const status = document.getElementById("section20-media-open-status");
  const player = document.getElementById("section20-media-player");

  check(region && input && pastedButton && localButton && player, "Section 20 Media surface did not mount");
  check(root.children.indexOf(region) < root.children.indexOf(originalMain), "Media workflow is not reachable before legacy main content");
  check(pastedButton.tagName === "BUTTON" && localButton.tagName === "BUTTON", "Media open actions are not native buttons");
  check(status.getAttribute("role") === "status", "Media open status is not an accessible status region");

  input.value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
  await pastedButton.listeners.click();
  await settle();

  check(opened.length === 1 && opened[0][0] === "pasted", "Pasted media did not reach the host exactly once");
  check(synchronized.length >= 1, "YouTube playback facts were not synchronized to the host");
  check(renders.some((entry) => entry.state.qualification === "confirmed"), "Confirmed synchronized player state was not rendered");
  check(!document.getElementById("product-media-restore-region"), "Restore-only duplicate surface appeared before fallback bootstrap");

  const youtubeRunner = player.__runner;
  await youtubeRunner({ action: "seek", positionMs: 40000 });
  await settle();
  check(providerCommands.some((item) => item[0] === "seek" && item[1] === 40000), "Exact seek did not go through the YouTube adapter");
  check(!hostCommands.some((item) => item[0] === "seek"), "Browser seek incorrectly crossed into host chess command authority");

  await youtubeRunner({ action: "restore" });
  await settle();
  check(hostCommands.some((item) => item[0] === "restore"), "Restore Media Position did not reach the canonical host workflow");

  await localButton.listeners.click();
  await settle();
  check(opened.some((item) => item[0] === "local"), "Local media open did not reach the host");
  const hostRunner = player.__runner;
  await hostRunner({ action: "pause" });
  check(hostCommands.some((item) => item[0] === "pause"), "Host media pause did not use the host workflow");

  vm.runInThisContext(
    fs.readFileSync("web/version2_media_restore_bootstrap.js", "utf8"),
    { filename: "version2_media_restore_bootstrap.js" },
  );
  check(!document.getElementById("product-media-restore-region"), "Legacy restore-only bootstrap was not suppressed by Section 20 workflow");

  console.log("version2_media_user_workflow_dom_test: ok");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
