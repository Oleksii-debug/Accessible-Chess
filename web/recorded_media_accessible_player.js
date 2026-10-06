"use strict";

(function (global) {
  const PLAY_ID = "recorded-media-play-toggle";
  const SEEK_ID = "recorded-media-seek";
  const BACK_ID = "recorded-media-seek-back";
  const FORWARD_ID = "recorded-media-seek-forward";
  const RESTORE_ID = "recorded-media-restore";
  const CANCEL_ID = "recorded-media-cancel";
  const STATUS_ID = "recorded-media-status";
  const PROGRESS_ID = "recorded-media-progress";
  const ANNOUNCEMENT_ID = "recorded-media-announcement";
  const generations = new WeakMap();

  function requiredText(value, name, limit = 4096) {
    if (typeof value !== "string" || !value || value.length > limit || value.includes("\u0000")) {
      throw new Error(`invalid ${name}`);
    }
    return value;
  }

  function optionalText(value, name, limit = 4096) {
    if (value === "") return "";
    return requiredText(value, name, limit);
  }

  function optionalSafeInteger(value, name) {
    if (value === null) return null;
    if (!Number.isSafeInteger(value) || value < 0) throw new Error(`invalid ${name}`);
    return value;
  }

  function validateState(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("invalid recorded-media player state");
    }
    if (typeof value.ok !== "boolean") throw new Error("invalid player ok flag");
    const revision = optionalSafeInteger(value.revision, "revision");
    const positionMs = optionalSafeInteger(value.positionMs, "positionMs");
    const durationMs = optionalSafeInteger(value.durationMs, "durationMs");
    if (durationMs !== null && positionMs !== null && positionMs > durationMs) {
      throw new Error("player position exceeds duration");
    }
    const playbackState = requiredText(value.playbackState, "playbackState", 32);
    if (!["unstarted", "playing", "paused", "buffering", "ended"].includes(playbackState)) {
      throw new Error("invalid playback state");
    }
    const qualification = requiredText(value.qualification, "qualification", 32);
    if (!["confirmed", "candidate", "ambiguous", "unlinked", "unavailable"].includes(qualification)) {
      throw new Error("invalid synchronization qualification");
    }
    const preprocessStatus = requiredText(value.preprocessStatus, "preprocessStatus", 32);
    if (!["running", "canceled", "complete", "unavailable"].includes(preprocessStatus)) {
      throw new Error("invalid preprocess status");
    }
    const completed = optionalSafeInteger(value.preprocessCompleted, "preprocessCompleted");
    const total = optionalSafeInteger(value.preprocessTotal, "preprocessTotal");
    if (completed === null || total === null || completed > total) {
      throw new Error("invalid preprocess progress");
    }
    for (const [name, flag] of [
      ["restoreEnabled", value.restoreEnabled],
      ["seekEnabled", value.seekEnabled],
      ["cancelEnabled", value.cancelEnabled],
    ]) {
      if (typeof flag !== "boolean") throw new Error(`invalid ${name}`);
    }
    const playAction = requiredText(value.playAction, "playAction", 16);
    if (!["play", "pause"].includes(playAction)) throw new Error("invalid play action");
    return {
      ok: value.ok,
      revision,
      positionMs,
      durationMs,
      positionText: optionalText(value.positionText, "positionText", 64),
      regionLabel: requiredText(value.regionLabel, "regionLabel", 256),
      heading: requiredText(value.heading, "heading", 256),
      seekLabel: requiredText(value.seekLabel, "seekLabel", 256),
      backLabel: requiredText(value.backLabel, "backLabel", 256),
      forwardLabel: requiredText(value.forwardLabel, "forwardLabel", 256),
      restoreLabel: requiredText(value.restoreLabel, "restoreLabel", 256),
      cancelLabel: requiredText(value.cancelLabel, "cancelLabel", 256),
      progressLabel: requiredText(value.progressLabel, "progressLabel", 256),
      playbackState,
      qualification,
      statusText: requiredText(value.statusText, "statusText"),
      restoreEnabled: value.restoreEnabled,
      playAction,
      playLabel: requiredText(value.playLabel, "playLabel", 256),
      seekEnabled: value.seekEnabled,
      cancelEnabled: value.cancelEnabled,
      preprocessStatus,
      preprocessCompleted: completed,
      preprocessTotal: total,
      progressText: requiredText(value.progressText, "progressText", 512),
      announcement: optionalText(value.announcement, "announcement"),
      focusTarget: requiredText(value.focusTarget, "focusTarget", 64),
    };
  }

  function nextGeneration(root) {
    const next = (generations.get(root) || 0) + 1;
    generations.set(root, next);
    return next;
  }

  function isCurrent(root, generation) {
    return generations.get(root) === generation;
  }

  function appendText(parent, tagName, id, text) {
    const element = document.createElement(tagName);
    element.id = id;
    element.textContent = text;
    parent.appendChild(element);
    return element;
  }

  function makeButton(parent, id, label, disabled, describedBy) {
    const button = document.createElement("button");
    button.id = id;
    button.setAttribute("type", "button");
    button.setAttribute("aria-describedby", describedBy);
    button.textContent = label;
    button.disabled = disabled;
    parent.appendChild(button);
    return button;
  }

  function focusTarget(root, targetId) {
    let target = root.querySelector(`#${targetId}`);
    if (!target || target.disabled) target = root.querySelector(`#${STATUS_ID}`);
    if (target && typeof target.focus === "function") target.focus();
  }

  function safeCommandResult(result) {
    if (result === undefined) return null;
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      throw new Error("recorded-media command returned invalid state");
    }
    return validateState(result);
  }

  function runCommand(root, generation, button, invokeCommand, command) {
    if (!isCurrent(root, generation) || button.disabled) return Promise.resolve();
    const previousDisabled = button.disabled;
    button.disabled = true;
    return Promise.resolve()
      .then(() => invokeCommand(command))
      .then((result) => {
        if (!isCurrent(root, generation)) return;
        const next = safeCommandResult(result);
        if (next !== null) {
          render(root, next, invokeCommand, true);
        }
      })
      .catch(() => {
        if (!isCurrent(root, generation)) return;
        const fallback = root.querySelector(`#${STATUS_ID}`);
        const announcement = root.querySelector(`#${ANNOUNCEMENT_ID}`);
        const failureText = "The recorded-media command result could not be confirmed. Check the current media and chess state.";
        if (fallback) fallback.textContent = failureText;
        if (announcement) announcement.textContent = failureText;
        button.disabled = previousDisabled;
      });
  }

  function render(root, value, invokeCommand, focusAfterRender) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new Error("recorded-media player root is unavailable");
    }
    if (typeof invokeCommand !== "function") {
      throw new Error("recorded-media command handler is unavailable");
    }
    const state = validateState(value);
    const generation = nextGeneration(root);

    const section = document.createElement("section");
    section.setAttribute("role", "region");
    section.setAttribute("aria-label", state.regionLabel);

    const heading = appendText(section, "h2", "recorded-media-heading", state.heading);
    section.setAttribute("aria-labelledby", heading.id);

    const position = appendText(section, "p", "recorded-media-position", state.positionText);
    if (state.positionMs !== null) {
      position.setAttribute("data-position-ms", String(state.positionMs));
    }

    const status = appendText(section, "p", STATUS_ID, state.statusText);
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("aria-atomic", "true");
    status.setAttribute("tabindex", "-1");

    if (state.positionMs !== null && state.durationMs !== null && state.durationMs > 0) {
      const seek = document.createElement("input");
      seek.id = SEEK_ID;
      seek.setAttribute("type", "range");
      seek.setAttribute("min", "0");
      seek.setAttribute("max", String(state.durationMs));
      seek.setAttribute("step", "1000");
      seek.setAttribute("aria-label", state.seekLabel);
      seek.setAttribute("aria-describedby", STATUS_ID);
      seek.setAttribute("aria-valuetext", state.positionText);
      seek.value = String(state.positionMs);
      seek.disabled = !state.seekEnabled;
      seek.addEventListener("change", () => {
        const numeric = Number(seek.value);
        if (!Number.isSafeInteger(numeric) || numeric < 0 || numeric > state.durationMs) {
          throw new Error("invalid seek value");
        }
        return runCommand(root, generation, seek, invokeCommand, {
          action: "seek",
          positionMs: numeric,
        });
      });
      section.appendChild(seek);

      const nav = document.createElement("div");
      const back = makeButton(nav, BACK_ID, state.backLabel, !state.seekEnabled, SEEK_ID);
      const forward = makeButton(nav, FORWARD_ID, state.forwardLabel, !state.seekEnabled, SEEK_ID);
      back.addEventListener("click", () => {
        return runCommand(root, generation, back, invokeCommand, {
          action: "seek",
          positionMs: Math.max(0, state.positionMs - 10_000),
        });
      });
      forward.addEventListener("click", () => {
        return runCommand(root, generation, forward, invokeCommand, {
          action: "seek",
          positionMs: Math.min(state.durationMs, state.positionMs + 10_000),
        });
      });
      section.appendChild(nav);
    }

    const controls = document.createElement("div");
    const play = makeButton(
      controls,
      PLAY_ID,
      state.playLabel,
      state.ok === false,
      STATUS_ID,
    );
    play.addEventListener("click", () => {
      return runCommand(root, generation, play, invokeCommand, { action: state.playAction });
    });
    makeButton(controls, RESTORE_ID, state.restoreLabel, !state.restoreEnabled, STATUS_ID)
      .addEventListener("click", function () {
        return runCommand(root, generation, this, invokeCommand, { action: "restore" });
      });
    makeButton(controls, CANCEL_ID, state.cancelLabel, !state.cancelEnabled, STATUS_ID)
      .addEventListener("click", function () {
        return runCommand(root, generation, this, invokeCommand, { action: "cancel" });
      });
    section.appendChild(controls);

    const progressText = appendText(section, "p", "recorded-media-progress-text", state.progressText);
    progressText.setAttribute("aria-describedby", PROGRESS_ID);

    const progress = document.createElement("progress");
    progress.id = PROGRESS_ID;
    progress.setAttribute("max", String(Math.max(1, state.preprocessTotal)));
    progress.value = state.preprocessCompleted;
    progress.setAttribute("aria-label", state.progressLabel);
    section.appendChild(progress);

    const announcement = appendText(section, "p", ANNOUNCEMENT_ID, state.announcement);
    announcement.setAttribute("aria-live", "assertive");
    announcement.setAttribute("aria-atomic", "true");

    root.replaceChildren(section);
    if (focusAfterRender) focusTarget(root, state.focusTarget);
  }

  global.AccessibleChessRecordedMediaPlayer = {
    render,
  };
})(typeof window !== "undefined" ? window : globalThis);
