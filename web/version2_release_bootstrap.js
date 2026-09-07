(function (global) {
  "use strict";
  if (global.__accessibleChessVersion2ReleaseInstalled) return;
  global.__accessibleChessVersion2ReleaseInstalled = true;

  const documentRef = global.document;
  const originalMain = documentRef.getElementById("main-content");
  const live = documentRef.getElementById("live");
  if (!originalMain || !live) return;

  let currentLanguage = documentRef.documentElement.lang === "en" ? "en" : "uk";
  let currentRouteId = "board";

  function uiText(uk, en) {
    return currentLanguage === "en" ? en : uk;
  }

  function api() {
    return global.pywebview && global.pywebview.api;
  }

  function announce(message) {
    if (!message) return;
    live.textContent = "";
    global.setTimeout(function () { live.textContent = String(message).slice(0, 300); }, 20);
  }

  const nav = documentRef.createElement("nav");
  nav.id = "v2-navigation";
  const navHeading = documentRef.createElement("h2");
  navHeading.id = "v2-navigation-heading";
  nav.appendChild(navHeading);
  const navList = documentRef.createElement("ul");
  navList.id = "v2-navigation-list";
  nav.appendChild(navList);

  const workspace = documentRef.createElement("main");
  workspace.id = "v2-workspace";
  workspace.setAttribute("aria-live", "off");
  workspace.hidden = true;

  originalMain.parentNode.insertBefore(nav, originalMain);
  originalMain.parentNode.insertBefore(workspace, originalMain);

  const stage1Focus = Object.freeze({
    board: "board-launcher",
    analysis: "h-engine",
    settings: "h-settings",
    help: "h-help"
  });

  function emptyStatusId(routeId) {
    if (routeId === "pgn" || routeId === "library" || routeId === "books") {
      return "v2-" + routeId + "-empty-status";
    }
    return "";
  }

  function hiddenByAncestor(target) {
    let node = target;
    while (node) {
      if (node.hidden) return true;
      node = node.parentNode;
    }
    return false;
  }

  function focusById(id) {
    if (!id) return false;
    const target = documentRef.getElementById(id);
    if (!target || hiddenByAncestor(target) || typeof target.focus !== "function") return false;
    if (!target.hasAttribute("tabindex") && !/^(BUTTON|INPUT|SELECT|TEXTAREA|A)$/.test(target.tagName)) {
      target.setAttribute("tabindex", "-1");
    }
    target.focus({ preventScroll: true });
    return documentRef.activeElement === target;
  }

  function restoreStage1Focus(routeId, requestedFocus) {
    if (focusById(requestedFocus)) return true;
    return focusById(stage1Focus[routeId] || "");
  }

  function productSurfaceFocusTarget(snapshot, routeId) {
    if (routeId === "pgn" && snapshot.pgn && typeof snapshot.pgn === "object") {
      return String(snapshot.pgn.focus_target || "");
    }
    if (routeId === "books" && snapshot.books && typeof snapshot.books === "object") {
      const block = snapshot.books.block && typeof snapshot.books.block === "object" ? snapshot.books.block : {};
      return String(block.dom_id || "");
    }
    return emptyStatusId(routeId);
  }

  function restoreProductFocus(snapshot, routeId, requestedFocus) {
    const active = documentRef.activeElement;
    if (active && workspace.contains(active)) return true;
    if (focusById(productSurfaceFocusTarget(snapshot, routeId))) return true;
    if (focusById(requestedFocus)) return true;
    return focusById("v2-nav-" + routeId);
  }

  function renderEmptyProduct(routeId, heading) {
    const title = documentRef.createElement("h2");
    const fallbackHeading = routeId === "pgn"
      ? "PGN"
      : routeId === "library"
        ? uiText("Бібліотека", "Library")
        : uiText("Книги", "Books");
    title.textContent = String(heading || fallbackHeading);
    const status = documentRef.createElement("p");
    status.id = emptyStatusId(routeId);
    status.tabIndex = -1;
    status.textContent = routeId === "pgn"
      ? uiText("PGN ще не відкрито.", "No PGN is open yet.")
      : routeId === "library"
        ? uiText("Бібліотека ще не готова до перегляду.", "The Library is not ready to browse yet.")
        : uiText("Книгу ще не відкрито.", "No book is open yet.");
    workspace.replaceChildren(title, status);
  }

  function areaInvoke(area) {
    return function (command, payload) {
      const bridge = api();
      if (!bridge || typeof bridge.v2_browser_command !== "function") {
        return Promise.reject(new Error("V2 bridge unavailable"));
      }
      return bridge.v2_browser_command(area, command, payload || {});
    };
  }

  function renderNavigation(snapshot) {
    const items = Array.isArray(snapshot.navigation) ? snapshot.navigation : [];
    const fragment = documentRef.createDocumentFragment();
    items.forEach(function (item) {
      const row = documentRef.createElement("li");
      const button = documentRef.createElement("button");
      button.type = "button";
      button.id = "v2-nav-" + String(item.route_id || "");
      button.textContent = String(item.label || item.route_id || "");
      if (String(item.current) === "true") button.setAttribute("aria-current", "page");
      button.addEventListener("click", function () {
        const bridge = api();
        if (!bridge || typeof bridge.v2_browser_command !== "function") return;
        bridge.v2_browser_command("shell", String(item.action_id || ""), {}).then(function (result) {
          if (result && result.kind === "error" && result.payload) announce(result.payload.message || "");
          refresh(true);
        }, function () { announce(uiText("Не вдалося відкрити розділ.", "Could not open the section.")); });
      });
      row.appendChild(button);
      fragment.appendChild(row);
    });
    navList.replaceChildren(fragment);
  }

  function renderProductSurface(snapshot, routeId, requestedFocus, restoreFocus, heading) {
    originalMain.hidden = true;
    workspace.hidden = false;
    if (routeId === "pgn") {
      if (snapshot.pgn && global.AccessibleChessPgnSurface) {
        global.AccessibleChessPgnSurface.render(workspace, snapshot.pgn, areaInvoke("pgn"), announce, requestedFocus || "");
      } else {
        renderEmptyProduct(routeId, heading);
      }
      if (restoreFocus) restoreProductFocus(snapshot, routeId, requestedFocus);
      return;
    }
    if (routeId === "library") {
      if (snapshot.library && global.AccessibleChessLibrarySurface) {
        global.AccessibleChessLibrarySurface.render(workspace, snapshot.library, areaInvoke("library"), announce, requestedFocus || "");
      } else {
        renderEmptyProduct(routeId, heading);
      }
      if (restoreFocus) restoreProductFocus(snapshot, routeId, requestedFocus);
      return;
    }
    if (routeId === "books") {
      if (snapshot.books && global.AccessibleChessBookSurface) {
        global.AccessibleChessBookSurface.render(workspace, snapshot.books, areaInvoke("books"), announce, requestedFocus || "");
      } else {
        renderEmptyProduct(routeId, heading);
      }
      if (restoreFocus) restoreProductFocus(snapshot, routeId, requestedFocus);
    }
  }

  function render(snapshot, restoreFocus) {
    if (!snapshot || typeof snapshot !== "object") return;
    currentLanguage = snapshot.document && snapshot.document.lang === "en" ? "en" : "uk";
    documentRef.documentElement.lang = currentLanguage;
    nav.setAttribute("aria-label", uiText("Розділи Accessible Chess", "Accessible Chess sections"));
    navHeading.textContent = uiText("Розділи", "Sections");
    renderNavigation(snapshot);
    const screen = snapshot.screen && typeof snapshot.screen === "object" ? snapshot.screen : {};
    const routeId = String(screen.route_id || "board");
    currentRouteId = routeId;
    const requestedFocus = String(screen.focus_target || "");
    const heading = String(screen.heading || "");

    if (routeId === "pgn" || routeId === "library" || routeId === "books") {
      renderProductSurface(snapshot, routeId, requestedFocus, restoreFocus, heading);
      return;
    }

    workspace.hidden = true;
    workspace.replaceChildren();
    originalMain.hidden = false;
    if (restoreFocus) restoreStage1Focus(routeId, requestedFocus);
  }

  function refresh(restoreFocus) {
    const bridge = api();
    if (!bridge || typeof bridge.v2_snapshot !== "function") return Promise.resolve();
    return bridge.v2_snapshot().then(function (snapshot) { render(snapshot, !!restoreFocus); });
  }

  function isVersion2DomainAction(actionId) {
    return actionId.indexOf("pgn.") === 0 || actionId.indexOf("library.") === 0 || actionId.indexOf("book.") === 0;
  }

  function refreshStage1Surface() {
    if (typeof global.refreshState !== "function") {
      announce(uiText("Не вдалося оновити дошку.", "Could not refresh the board."));
      return;
    }
    Promise.resolve(global.refreshState()).catch(function () {
      announce(uiText("Не вдалося оновити дошку.", "Could not refresh the board."));
    });
  }

  function applyQueuedEvent(event) {
    if (!event || typeof event !== "object") return false;
    const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
    if (event.kind === "render-import") {
      if (currentRouteId === "library" && global.AccessibleChessLibrarySurface &&
          typeof global.AccessibleChessLibrarySurface.apply === "function") {
        try {
          global.AccessibleChessLibrarySurface.apply(workspace, event, areaInvoke("library"), announce);
        } catch (_) {
          return true;
        }
      } else if (payload.announcement) {
        announce(payload.announcement);
      }
      return false;
    }
    if (event.kind === "delegated") {
      const actionId = typeof payload.action_id === "string" ? payload.action_id : "";
      if (actionId && !isVersion2DomainAction(actionId)) {
        refreshStage1Surface();
        return false;
      }
    }
    if (payload.announcement) announce(payload.announcement);
    if (event.kind === "error" && payload.message) announce(payload.message);
    return event.kind !== "error" && event.kind !== "status";
  }

  function drainEvents() {
    const bridge = api();
    if (!bridge || typeof bridge.v2_drain_events !== "function") return;
    bridge.v2_drain_events().then(function (events) {
      if (!Array.isArray(events) || !events.length) return;
      let needsRefresh = false;
      let queuedFocusTarget = "";
      events.forEach(function (event) {
        const refreshRequired = applyQueuedEvent(event);
        if (!refreshRequired) return;
        needsRefresh = true;
        const payload = event && event.payload && typeof event.payload === "object" ? event.payload : {};
        const candidate = typeof payload.focus_target === "string" ? payload.focus_target : "";
        if (candidate) queuedFocusTarget = candidate;
      });
      if (needsRefresh) {
        refresh(true).then(function () {
          if (queuedFocusTarget) focusById(queuedFocusTarget);
        }, function () {});
      }
    }, function () {});
  }

  documentRef.addEventListener("focusin", function (event) {
    const target = event.target;
    if (!target || !target.id || !/^[A-Za-z0-9_-]{1,160}$/.test(target.id)) return;
    if (target.id.indexOf("v2-nav-") === 0) return;
    const bridge = api();
    if (bridge && typeof bridge.v2_record_focus === "function") {
      bridge.v2_record_focus(target.id).catch(function () {});
    }
  }, true);

  refresh(true).catch(function () {
    announce(uiText("Не вдалося завантажити розділи Version 2.", "Could not load Version 2 sections."));
  });
  global.setInterval(drainEvents, 300);
})(window);