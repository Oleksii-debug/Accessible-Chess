(function (global) {
  "use strict";
  if (global.__accessibleChessSection20MediaWorkflowInstalled) return;
  if (global.__accessibleChessProductMediaRestoreInstalled) return;
  global.__accessibleChessProductMediaRestoreInstalled = true;

  const documentRef = global.document;
  const workspace = documentRef.getElementById("v2-workspace");
  const originalMain = documentRef.getElementById("main-content");
  const parent = workspace && workspace.parentNode
    ? workspace.parentNode
    : originalMain && originalMain.parentNode
      ? originalMain.parentNode
      : null;
  if (!parent) return;

  const region = documentRef.createElement("section");
  region.id = "product-media-restore-region";
  region.setAttribute("aria-label", "Media");
  const host = documentRef.createElement("div");
  host.id = "product-media-restore-surface";
  region.appendChild(host);

  if (originalMain && originalMain.parentNode === parent) {
    parent.insertBefore(region, originalMain);
  } else {
    parent.appendChild(region);
  }

  function language() {
    return documentRef.documentElement && documentRef.documentElement.lang === "en"
      ? "en"
      : "uk";
  }

  function unavailableText() {
    return language() === "en"
      ? "Media synchronization is currently unavailable. The chess position was not changed."
      : "Синхронізація медіа зараз недоступна. Шахову позицію не змінено.";
  }

  function renderUnavailable() {
    const status = documentRef.createElement("p");
    status.id = "media-sync-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("aria-atomic", "true");
    status.setAttribute("tabindex", "-1");
    status.textContent = unavailableText();
    host.replaceChildren(status);
    return false;
  }

  function bridge() {
    return global.pywebview && global.pywebview.api;
  }

  function renderer() {
    const value = global.AccessibleChessMediaRestoreSurface;
    return value && typeof value.render === "function" ? value : null;
  }

  function invokeRestore() {
    const api = bridge();
    if (!api || typeof api.media_restore_position !== "function") {
      return Promise.reject(new Error("Media restore bridge unavailable"));
    }
    return api.media_restore_position();
  }

  function refresh(focusAfterRender) {
    const api = bridge();
    const surface = renderer();
    if (!api || typeof api.media_restore_snapshot !== "function" || !surface) {
      renderUnavailable();
      return Promise.resolve(false);
    }
    return api.media_restore_snapshot().then(function (state) {
      surface.render(host, state, invokeRestore, focusAfterRender === true);
      return true;
    }).catch(function () {
      renderUnavailable();
      return false;
    });
  }

  global.AccessibleChessProductMediaRestore = Object.freeze({ refresh: refresh });
  refresh(false);
})(window);
