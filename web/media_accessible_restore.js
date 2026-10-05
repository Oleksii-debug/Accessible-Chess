"use strict";

(function (global) {
  const RESTORE_ID = "media-restore-position";
  const STATUS_ID = "media-sync-status";
  const ANNOUNCEMENT_ID = "media-restore-announcement";

  function requiredText(value, name) {
    if (typeof value !== "string" || !value || value.length > 4096 || value.includes("\u0000")) {
      throw new Error(`invalid ${name}`);
    }
    return value;
  }

  function optionalText(value, name) {
    if (typeof value !== "string" || value.length > 4096 || value.includes("\u0000")) {
      throw new Error(`invalid ${name}`);
    }
    return value;
  }

  function validateState(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("invalid media accessibility state");
    }
    if (typeof value.ok !== "boolean" || typeof value.restoreEnabled !== "boolean") {
      throw new Error("invalid media accessibility flags");
    }
    if (value.revision !== null && (!Number.isSafeInteger(value.revision) || value.revision < 0)) {
      throw new Error("invalid media accessibility revision");
    }
    if (value.positionMs !== null && (!Number.isSafeInteger(value.positionMs) || value.positionMs < 0)) {
      throw new Error("invalid media accessibility position");
    }
    const qualification = requiredText(value.qualification, "qualification");
    if (!["confirmed", "candidate", "ambiguous", "unlinked", "unavailable"].includes(qualification)) {
      throw new Error("invalid media accessibility qualification");
    }
    const focusTarget = requiredText(value.focusTarget, "focusTarget");
    if (![RESTORE_ID, STATUS_ID].includes(focusTarget)) {
      throw new Error("invalid media accessibility focus target");
    }
    return {
      ok: value.ok,
      revision: value.revision,
      positionMs: value.positionMs,
      positionText: optionalText(value.positionText, "positionText"),
      qualification,
      restoreEnabled: value.restoreEnabled,
      restoreLabel: requiredText(value.restoreLabel, "restoreLabel"),
      restoreDescription: requiredText(value.restoreDescription, "restoreDescription"),
      statusText: requiredText(value.statusText, "statusText"),
      announcement: optionalText(value.announcement, "announcement"),
      focusTarget,
    };
  }

  function appendText(parent, tagName, id, text) {
    const node = document.createElement(tagName);
    node.id = id;
    node.textContent = text;
    parent.appendChild(node);
    return node;
  }

  function restoreFocus(root, targetId) {
    let target = root.querySelector(`#${targetId}`);
    if (!target || target.disabled) {
      target = root.querySelector(`#${STATUS_ID}`);
    }
    if (target && typeof target.focus === "function") target.focus();
  }

  function transportFailureText(label) {
    return label === "Відновити позицію медіа"
      ? "Не вдалося виконати команду відновлення позиції медіа. Нічого не змінено."
      : "The Restore Media Position command failed. Nothing was changed.";
  }

  function render(root, value, invokeRestore, focusAfterRender) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new Error("media restore root is unavailable");
    }
    if (typeof invokeRestore !== "function") {
      throw new Error("media restore command is unavailable");
    }
    const state = validateState(value);
    const region = document.createElement("section");
    region.setAttribute("aria-label", state.restoreLabel);

    const position = appendText(region, "p", "media-position-text", state.positionText);
    position.setAttribute("data-media-position-ms", state.positionMs === null ? "" : String(state.positionMs));

    const status = appendText(region, "p", STATUS_ID, state.statusText);
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("aria-atomic", "true");
    status.setAttribute("tabindex", "-1");
    status.setAttribute("data-media-qualification", state.qualification);

    const restore = document.createElement("button");
    restore.id = RESTORE_ID;
    restore.setAttribute("type", "button");
    restore.setAttribute("aria-describedby", STATUS_ID);
    restore.setAttribute("title", state.restoreDescription);
    restore.textContent = state.restoreLabel;
    restore.disabled = !state.restoreEnabled;
    region.appendChild(restore);

    const announcement = appendText(region, "p", ANNOUNCEMENT_ID, state.announcement);
    announcement.setAttribute("role", "status");
    announcement.setAttribute("aria-live", "assertive");
    announcement.setAttribute("aria-atomic", "true");
    announcement.setAttribute("tabindex", "-1");

    let busy = false;
    restore.addEventListener("click", async () => {
      if (busy || restore.disabled) return;
      busy = true;
      restore.disabled = true;
      restore.setAttribute("aria-busy", "true");
      try {
        const next = await invokeRestore();
        render(root, next, invokeRestore, true);
      } catch (_error) {
        busy = false;
        restore.removeAttribute("aria-busy");
        restore.disabled = !state.restoreEnabled;
        announcement.textContent = transportFailureText(state.restoreLabel);
        announcement.focus();
      }
    });

    root.replaceChildren(region);
    if (focusAfterRender === true) restoreFocus(root, state.focusTarget);
    return state;
  }

  global.AccessibleChessMediaRestoreSurface = Object.freeze({ render });
})(window);
