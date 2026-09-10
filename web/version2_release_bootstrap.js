(function (global) {
  "use strict";
  if (global.__accessibleChessVersion2ReleaseInstalled) return;
  global.__accessibleChessVersion2ReleaseInstalled = true;

  const documentRef = global.document;
  const originalMain = documentRef.getElementById("main-content");
  const live = documentRef.getElementById("live");
  if (!originalMain || !live) return;

  let currentLanguage = documentRef.documentElement.lang === "en" ? "en" : "uk";

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

  const workspace = documentRef.createElement("section");
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

  function focusById(id) {
    if (!id) return;
    const target = documentRef.getElementById(id);
    if (!target || typeof target.focus !== "function") return;
    if (!target.hasAttribute("tabindex") && !/^(BUTTON|INPUT|SELECT|TEXTAREA|A)$/.test(target.tagName)) {
      target.setAttribute("tabindex", "-1");
    }
    target.focus({ preventScroll: true });
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

  function renderProductSurface(snapshot, routeId, requestedFocus) {
    workspace.hidden = false;
    originalMain.hidden = true;
    if (routeId === "pgn") {
      if (snapshot.pgn && global.AccessibleChessPgnSurface) {
        global.AccessibleChessPgnSurface.render(workspace, snapshot.pgn, areaInvoke("pgn"), announce, requestedFocus || "");
      } else {
        workspace.replaceChildren(Object.assign(documentRef.createElement("p"), {
          textContent: uiText("PGN ще не відкрито.", "No PGN is open yet.")
        }));
      }
      return;
    }
    if (routeId === "library") {
      if (snapshot.library && global.AccessibleChessLibrarySurface) {
        global.AccessibleChessLibrarySurface.render(workspace, snapshot.library, areaInvoke("library"), announce, requestedFocus || "");
      }
      return;
    }
    if (routeId === "books") {
      if (snapshot.books && global.AccessibleChessBookSurface) {
        global.AccessibleChessBookSurface.render(workspace, snapshot.books, areaInvoke("books"), announce, requestedFocus || "");
      } else {
        workspace.replaceChildren(Object.assign(documentRef.createElement("p"), {
          textContent: uiText("Книгу ще не відкрито.", "No book is open yet.")
        }));
      }
      return;
    }
    if (routeId === "training") {
      if (snapshot.training && global.AccessibleChessTrainingSurface) {
        const trainingFocus = requestedFocus === "training-prompt" ? "training-answer" : requestedFocus;
        global.AccessibleChessTrainingSurface.render(
          workspace,
          snapshot.training,
          areaInvoke("training"),
          announce,
          trainingFocus || "training-answer"
        );
      } else {
        workspace.replaceChildren(Object.assign(documentRef.createElement("p"), {
          textContent: uiText(
            "У відкритій книзі немає доступних шахових вправ.",
            "The open book has no available chess exercises."
          )
        }));
      }
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
    const requestedFocus = String(screen.focus_target || "");

    if (routeId === "pgn" || routeId === "library" || routeId === "books" || routeId === "training") {
      renderProductSurface(snapshot, routeId, requestedFocus);
      return;
    }

    workspace.hidden = true;
    workspace.replaceChildren();
    originalMain.hidden = false;
    if (restoreFocus) focusById(stage1Focus[routeId] || requestedFocus);
  }

  function refresh(restoreFocus) {
    const bridge = api();
    if (!bridge || typeof bridge.v2_snapshot !== "function") return Promise.resolve();
    return bridge.v2_snapshot().then(function (snapshot) { render(snapshot, !!restoreFocus); });
  }

  function drainEvents() {
    const bridge = api();
    if (!bridge || typeof bridge.v2_drain_events !== "function") return;
    bridge.v2_drain_events().then(function (events) {
      if (!Array.isArray(events) || !events.length) return;
      events.forEach(function (event) {
        const payload = event && event.payload && typeof event.payload === "object" ? event.payload : {};
        if (payload.announcement) announce(payload.announcement);
        if (event && event.kind === "error" && payload.message) announce(payload.message);
      });
      refresh(false);
    }, function () {});
  }

  documentRef.addEventListener("focusin", function (event) {
    const target = event.target;
    if (!target || !target.id || !/^[A-Za-z0-9_-]{1,160}$/.test(target.id)) return;
    const bridge = api();
    if (bridge && typeof bridge.v2_record_focus === "function") {
      bridge.v2_record_focus(target.id).catch(function () {});
    }
  }, true);

  refresh(false).catch(function () {
    announce(uiText("Не вдалося завантажити розділи Version 2.", "Could not load Version 2 sections."));
  });
  global.setInterval(drainEvents, 300);
})(window);