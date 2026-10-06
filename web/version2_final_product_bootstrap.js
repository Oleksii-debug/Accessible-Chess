(function (global) {
  "use strict";
  if (global.__accessibleChessVersion2FinalProductInstalled) return;
  global.__accessibleChessVersion2FinalProductInstalled = true;

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
    const text = boundedText(message, MAX_ANNOUNCEMENT_TEXT);
    if (!text) return;
    live.textContent = "";
    global.setTimeout(function () { live.textContent = text; }, 20);
  }

  const nav = documentRef.createElement("nav");
  nav.id = "v2-navigation";
  const navHeading = documentRef.createElement("h2");
  navHeading.id = "v2-navigation-heading";
  nav.appendChild(navHeading);
  const navList = documentRef.createElement("div");
  navList.id = "v2-navigation-list";
  nav.appendChild(navList);

  const workspace = documentRef.createElement("main");
  workspace.id = "v2-workspace";
  workspace.setAttribute("aria-live", "off");
  workspace.hidden = true;

  originalMain.parentNode.insertBefore(nav, originalMain);
  originalMain.parentNode.insertBefore(workspace, originalMain);

  const selectionStyle = documentRef.createElement("style");
  selectionStyle.id = "v2-semantic-selection-style";
  selectionStyle.textContent = [
    "#main-content, #v2-workspace, #v2-navigation,",
    "#v2-navigation h2, #v2-navigation li, #v2-navigation button,",
    "#main-content p, #main-content div, #main-content span, #main-content li, #main-content button,",
    "#main-content h1, #main-content h2, #main-content h3, #main-content pre, #main-content code,",
    "#v2-workspace p, #v2-workspace div, #v2-workspace span, #v2-workspace li, #v2-workspace button,",
    "#v2-workspace h1, #v2-workspace h2, #v2-workspace h3, #v2-workspace pre, #v2-workspace code {",
    "  -webkit-user-select: text !important;",
    "  user-select: text !important;",
    "}"
  ].join("\n");
  (documentRef.head || documentRef.documentElement).appendChild(selectionStyle);

  function currentSelection() {
    try {
      return typeof global.getSelection === "function" ? global.getSelection() : null;
    } catch (_) {
      return null;
    }
  }

  function textOffset(root, container, offset) {
    const probe = documentRef.createRange();
    probe.selectNodeContents(root);
    probe.setEnd(container, offset);
    return probe.toString().length;
  }

  function captureWorkspaceSelection() {
    const selection = currentSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount !== 1) return null;
    const range = selection.getRangeAt(0);
    try {
      if (!workspace.contains(range.startContainer) || !workspace.contains(range.endContainer)) return null;
      const chosenText = String(range.toString() || "");
      if (!chosenText.trim()) return null;
      const start = textOffset(workspace, range.startContainer, range.startOffset);
      const end = textOffset(workspace, range.endContainer, range.endOffset);
      if (end <= start) return null;
      const context = selectionContext(String(workspace.textContent || ""), start, end);
      let backward = false;
      if (
        selection.anchorNode &&
        selection.focusNode &&
        workspace.contains(selection.anchorNode) &&
        workspace.contains(selection.focusNode)
      ) {
        const anchor = textOffset(workspace, selection.anchorNode, selection.anchorOffset);
        const focus = textOffset(workspace, selection.focusNode, selection.focusOffset);
        backward = anchor > focus;
      }
      return {
        routeId: currentRouteId,
        start: start,
        end: end,
        text: chosenText,
        before: context.before,
        after: context.after,
        backward: backward
      };
    } catch (_) {
      return null;
    }
  }

  function textPoint(root, targetOffset) {
    const showText = global.NodeFilter ? global.NodeFilter.SHOW_TEXT : 4;
    const walker = documentRef.createTreeWalker(root, showText);
    let remaining = Math.max(0, Number(targetOffset) || 0);
    let lastText = null;
    while (walker.nextNode()) {
      const node = walker.currentNode;
      lastText = node;
      const length = String(node.data || "").length;
      if (remaining <= length) return {node: node, offset: remaining};
      remaining -= length;
    }
    if (lastText) return {node: lastText, offset: String(lastText.data || "").length};
    return {node: root, offset: 0};
  }

  const SELECTION_CONTEXT_CHARS = 48;

  function selectionContext(fullText, start, end) {
    return {
      before: fullText.slice(Math.max(0, start - SELECTION_CONTEXT_CHARS), start),
      after: fullText.slice(end, Math.min(fullText.length, end + SELECTION_CONTEXT_CHARS))
    };
  }

  function contextMatchScore(fullText, selectedText, start, before, after) {
    const expectedBefore = String(before || "");
    const expectedAfter = String(after || "");
    const left = fullText.slice(Math.max(0, start - expectedBefore.length), start);
    const rightStart = start + selectedText.length;
    const right = fullText.slice(rightStart, Math.min(fullText.length, rightStart + expectedAfter.length));
    let leftScore = 0;
    while (
      leftScore < left.length &&
      leftScore < expectedBefore.length &&
      left[left.length - 1 - leftScore] === expectedBefore[expectedBefore.length - 1 - leftScore]
    ) {
      leftScore += 1;
    }
    let rightScore = 0;
    while (
      rightScore < right.length &&
      rightScore < expectedAfter.length &&
      right[rightScore] === expectedAfter[rightScore]
    ) {
      rightScore += 1;
    }
    return leftScore + rightScore;
  }

  function nearestSelectionStart(fullText, selectedText, preferredStart, before, after) {
    if (!selectedText) return -1;
    let match = fullText.indexOf(selectedText);
    if (match < 0) return -1;
    let best = -1;
    let bestScore = -1;
    let bestScoreCount = 0;
    let candidateCount = 0;
    while (match >= 0) {
      candidateCount += 1;
      if (candidateCount > 4096) return -1;
      const score = contextMatchScore(fullText, selectedText, match, before, after);
      if (score > bestScore) {
        best = match;
        bestScore = score;
        bestScoreCount = 1;
      } else if (score === bestScore) {
        bestScoreCount += 1;
      }
      match = fullText.indexOf(selectedText, match + 1);
    }
    // A stale absolute offset is not semantic identity. If retained context
    // cannot distinguish equal candidates after rerender, do not guess.
    return bestScoreCount === 1 ? best : -1;
  }

  function restoreWorkspaceSelection(snapshot, routeId) {
    if (!snapshot || snapshot.routeId !== routeId || workspace.hidden) return false;
    const selection = currentSelection();
    if (!selection) return false;
    try {
      const fullText = String(workspace.textContent || "");
      let start = Math.max(0, Math.min(snapshot.start, fullText.length));
      let end = Math.max(start, Math.min(snapshot.end, fullText.length));
      if (snapshot.text) {
        const candidateStart = nearestSelectionStart(
          fullText,
          snapshot.text,
          start,
          snapshot.before,
          snapshot.after
        );
        if (candidateStart < 0) return false;
        start = candidateStart;
        end = Math.min(fullText.length, start + snapshot.text.length);
      }
      const startPoint = textPoint(workspace, start);
      const endPoint = textPoint(workspace, end);
      const range = documentRef.createRange();
      range.setStart(startPoint.node, startPoint.offset);
      range.setEnd(endPoint.node, endPoint.offset);
      if (snapshot.backward && typeof selection.setBaseAndExtent === "function") {
        selection.setBaseAndExtent(
          endPoint.node,
          endPoint.offset,
          startPoint.node,
          startPoint.offset
        );
      } else if (
        snapshot.backward &&
        typeof selection.collapse === "function" &&
        typeof selection.extend === "function"
      ) {
        selection.removeAllRanges();
        selection.addRange(range);
        selection.collapse(endPoint.node, endPoint.offset);
        selection.extend(startPoint.node, startPoint.offset);
      } else {
        selection.removeAllRanges();
        selection.addRange(range);
      }
      return String(selection.toString() || "") === snapshot.text;
    } catch (_) {
      return false;
    }
  }

  const stage1Focus = Object.freeze({
    board: "board-launcher",
    analysis: "h-engine",
    settings: "h-settings",
    help: "h-help"
  });

  const productRoutes = new Set(["pgn", "library", "books", "training", "teacher", "classes"]);

  function emptyStatusId(routeId) {
    return productRoutes.has(routeId) ? "v2-" + routeId + "-empty-status" : "";
  }

  function hiddenByAncestor(target) {
    let node = target;
    while (node) {
      if (node.hidden) return true;
      node = node.parentNode;
    }
    return false;
  }

  const FOCUS_ID_PATTERN = /^[A-Za-z0-9_-]{1,160}$/;
  const ROUTE_ID_PATTERN = /^[a-z][a-z0-9_-]{0,63}$/;
  const ACTION_ID_PATTERN = /^[a-z][a-z0-9_.-]{0,127}$/;
  const MAX_NATIVE_EVENT_BATCH = 64;
  const MAX_NAVIGATION_ITEMS = 32;
  const MAX_NAVIGATION_LABEL = 240;
  const MAX_SCREEN_HEADING = 600;
  const MAX_ANNOUNCEMENT_TEXT = 1200;
  const NATIVE_EVENT_KINDS = new Set([
    "route",
    "delegated",
    "book-board",
    "render-import",
    "status",
    "error",
    "render",
    "dialog-open",
    "dialog-close"
  ]);

  function validFocusId(value) {
    return typeof value === "string" && FOCUS_ID_PATTERN.test(value);
  }

  function validRouteId(value) {
    return typeof value === "string" && ROUTE_ID_PATTERN.test(value);
  }

  function validActionId(value) {
    return typeof value === "string" && ACTION_ID_PATTERN.test(value);
  }

  function boundedText(value, limit) {
    return typeof value === "string" &&
      value.length <= limit &&
      value.indexOf("\x00") < 0
      ? value
      : "";
  }

  function plainObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function focusById(id) {
    if (!validFocusId(id)) return false;
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
      return validFocusId(snapshot.pgn.focus_target) ? snapshot.pgn.focus_target : "";
    }
    if (routeId === "books" && snapshot.books && typeof snapshot.books === "object") {
      const block = snapshot.books.block && typeof snapshot.books.block === "object" ? snapshot.books.block : {};
      return validFocusId(block.dom_id) ? block.dom_id : "";
    }
    if (routeId === "training" && snapshot.training && typeof snapshot.training === "object") {
      return "training-answer";
    }
    if (routeId === "teacher" && snapshot.teacher && typeof snapshot.teacher === "object") {
      return "teacher-pointer-input";
    }
    if (routeId === "classes" && snapshot.education && typeof snapshot.education === "object") {
      const sections = Array.isArray(snapshot.education.sections) ? snapshot.education.sections : [];
      for (let index = 0; index < sections.length; index += 1) {
        const items = Array.isArray(sections[index].items) ? sections[index].items : [];
        if (items.length && validFocusId(items[0].dom_id)) return items[0].dom_id;
      }
    }
    return emptyStatusId(routeId);
  }

  function restoreProductFocus(snapshot, routeId, requestedFocus) {
    const active = documentRef.activeElement;
    if (active && workspace.contains(active)) return true;
    if (focusById(requestedFocus)) return true;
    if (focusById(productSurfaceFocusTarget(snapshot, routeId))) return true;
    return focusById("v2-nav-" + routeId);
  }

  function renderEmptyProduct(routeId, heading, status) {
    const title = documentRef.createElement("h2");
    const labels = {
      pgn: "PGN",
      library: uiText("Бібліотека", "Library"),
      books: uiText("Книги", "Books"),
      training: uiText("Тренування", "Training"),
      teacher: uiText("Режим викладача", "Teacher mode"),
      classes: uiText("Класи й учні", "Classes and students")
    };
    title.textContent = String(heading || labels[routeId] || routeId);
    const message = documentRef.createElement("p");
    message.id = emptyStatusId(routeId);
    message.tabIndex = -1;
    message.setAttribute("role", "status");
    if (status) {
      message.textContent = status;
    } else if (routeId === "pgn") {
      message.textContent = uiText("PGN ще не відкрито.", "No PGN is open yet.");
    } else if (routeId === "library") {
      message.textContent = uiText("Бібліотека ще не готова до перегляду.", "The Library is not ready to browse yet.");
    } else if (routeId === "training") {
      message.textContent = uiText(
        "Відкрийте книгу, перейдіть до блоку «Вправа», а потім відкрийте Тренування.",
        "Open a book, move to an Exercise block, then open Training."
      );
    } else if (routeId === "teacher") {
      message.textContent = uiText(
        "Немає активного заняття. Режим викладача стане доступним після відкриття канонічного заняття.",
        "No teaching session is active. Teacher mode becomes available after a canonical session is opened."
      );
    } else if (routeId === "classes") {
      message.textContent = uiText(
        "Дані класів недоступні. Існуючий файл не буде перезаписано автоматично.",
        "Classes data is unavailable. Existing data will not be overwritten automatically."
      );
    } else {
      message.textContent = uiText("Книгу ще не відкрито.", "No book is open yet.");
    }
    workspace.replaceChildren(title, message);
  }

  function areaInvoke(area) {
    return function (command, payload) {
      const bridge = api();
      if (!bridge || typeof bridge.v2_browser_command !== "function") {
        return Promise.reject(new Error("V2 bridge unavailable"));
      }
      return bridge.v2_browser_command(area, command, payload || {}).then(function (result) {
        if (area === "library" && command === "library.open_game" &&
            result && result.kind !== "error") {
          return refresh(true).then(function () { return result; });
        }
        return result;
      });
    };
  }

  function renderNavigation(snapshot) {
    if (!Array.isArray(snapshot.navigation) ||
        snapshot.navigation.length < 1 ||
        snapshot.navigation.length > MAX_NAVIGATION_ITEMS) {
      throw new TypeError("V2 navigation schema is invalid");
    }
    const routeIds = new Set();
    const currentRouteIds = new Set();
    const fragment = documentRef.createDocumentFragment();
    snapshot.navigation.forEach(function (item) {
      if (!plainObject(item)) {
        throw new TypeError("V2 navigation item is invalid");
      }
      const routeId = item.route_id;
      const actionId = item.action_id;
      const label = boundedText(item.label, MAX_NAVIGATION_LABEL);
      const current =
        item.current === true || item.current === "true"
          ? true
          : item.current === false || item.current === "false"
            ? false
            : null;
      if (!validRouteId(routeId) || !validActionId(actionId) || !label ||
          current === null || routeIds.has(routeId)) {
        throw new TypeError("V2 navigation item is invalid");
      }
      routeIds.add(routeId);
      if (current) currentRouteIds.add(routeId);

      const row = documentRef.createElement("div");
      const button = documentRef.createElement("button");
      button.type = "button";
      button.id = "v2-nav-" + routeId;
      button.textContent = label;
      if (current) button.setAttribute("aria-current", "page");
      button.addEventListener("click", function () {
        const bridge = api();
        if (!bridge || typeof bridge.v2_browser_command !== "function") return;
        bridge.v2_browser_command("shell", actionId, {}).then(function (result) {
          if (result && result.kind === "error" && result.payload) announce(result.payload.message || "");
          refresh(true);
        }, function () { announce(uiText("Не вдалося відкрити розділ.", "Could not open the section.")); });
      });
      row.appendChild(button);
      fragment.appendChild(row);
    });
    return {
      routeIds: routeIds,
      currentRouteIds: currentRouteIds,
      fragment: fragment
    };
  }

  function renderProductSurface(snapshot, routeId, requestedFocus, restoreFocus, heading) {
    const workspaceWasHidden = workspace.hidden;
    const originalMainWasHidden = originalMain.hidden;
    const previousWorkspaceNodes = Array.from(
      workspace.childNodes || workspace.children || []
    );
    const previousActiveElement = documentRef.activeElement;

    try {
      if (routeId === "pgn") {
        if (snapshot.pgn && global.AccessibleChessPgnSurface) {
          global.AccessibleChessPgnSurface.render(workspace, snapshot.pgn, areaInvoke("pgn"), announce, requestedFocus || "");
        } else {
          renderEmptyProduct(routeId, heading);
        }
      } else if (routeId === "library") {
        if (snapshot.library && global.AccessibleChessLibrarySurface) {
          global.AccessibleChessLibrarySurface.render(workspace, snapshot.library, areaInvoke("library"), announce, requestedFocus || "");
        } else {
          renderEmptyProduct(routeId, heading);
        }
      } else if (routeId === "books") {
        if (snapshot.books && global.AccessibleChessBookSurface) {
          global.AccessibleChessBookSurface.render(workspace, snapshot.books, areaInvoke("books"), announce, requestedFocus || "");
        } else {
          renderEmptyProduct(routeId, heading);
        }
      } else if (routeId === "training") {
        const focus = requestedFocus === "training-prompt" ? "training-answer" : requestedFocus;
        if (snapshot.training && global.AccessibleChessTrainingSurface) {
          global.AccessibleChessTrainingSurface.render(
            workspace, snapshot.training, areaInvoke("training"), announce, focus || "training-answer"
          );
          requestedFocus = focus;
        } else {
          renderEmptyProduct(routeId, heading);
        }
      } else if (routeId === "teacher") {
        if (snapshot.teacher && global.AccessibleChessTeacherSurface) {
          global.AccessibleChessTeacherSurface.render(
            workspace, snapshot.teacher, areaInvoke("teacher"), announce, requestedFocus || ""
          );
        } else {
          renderEmptyProduct(routeId, heading);
        }
      } else if (routeId === "classes") {
        if (snapshot.education && global.AccessibleChessEducationSurface) {
          global.AccessibleChessEducationSurface.render(
            workspace,
            snapshot.education,
            areaInvoke("classes"),
            announce,
            requestedFocus || "",
            uiText("Не вдалося виконати дію з класами.", "Could not complete the Classes action.")
          );
        } else {
          renderEmptyProduct(routeId, heading);
        }
      }

      originalMain.hidden = true;
      workspace.hidden = false;
      if (restoreFocus || workspaceWasHidden) {
        restoreProductFocus(snapshot, routeId, requestedFocus);
      }
    } catch (error) {
      try {
        workspace.replaceChildren(...previousWorkspaceNodes);
      } catch (_) {}
      workspace.hidden = workspaceWasHidden;
      originalMain.hidden = originalMainWasHidden;
      if (
        previousActiveElement &&
        typeof previousActiveElement.focus === "function" &&
        !hiddenByAncestor(previousActiveElement)
      ) {
        try {
          previousActiveElement.focus({ preventScroll: true });
        } catch (_) {}
      }
      throw error;
    }
  }

  function render(snapshot, restoreFocus) {
    if (!plainObject(snapshot)) return;
    const selectionSnapshot = captureWorkspaceSelection();
    const previousLanguage = currentLanguage;
    const previousDocumentLanguage = documentRef.documentElement.lang;
    const previousRouteId = currentRouteId;
    const previousNavigationNodes = Array.from(
      navList.childNodes || navList.children || []
    );
    const previousNavigationHeading = navHeading.textContent;

    try {
      currentLanguage = snapshot.document && snapshot.document.lang === "en" ? "en" : "uk";
      documentRef.documentElement.lang = currentLanguage;
      nav.setAttribute("aria-label", uiText("Розділи Accessible Chess", "Accessible Chess sections"));
      navHeading.textContent = uiText("Розділи", "Sections");
      const navigationState = renderNavigation(snapshot);
      const screen = plainObject(snapshot.screen) ? snapshot.screen : {};
      const routeId = screen.route_id;
      const requestedFocus = validFocusId(screen.focus_target) ? screen.focus_target : "";
      const heading = boundedText(screen.heading, MAX_SCREEN_HEADING);
      if (!validRouteId(routeId) || !heading ||
          !navigationState.routeIds.has(routeId) ||
          navigationState.currentRouteIds.size !== 1 ||
          !navigationState.currentRouteIds.has(routeId)) {
        throw new TypeError("V2 screen schema is invalid");
      }
      navList.replaceChildren(navigationState.fragment);
      currentRouteId = routeId;
      if (typeof global.showStage1Route === "function") global.showStage1Route(routeId);

      if (productRoutes.has(routeId)) {
        renderProductSurface(snapshot, routeId, requestedFocus, restoreFocus, heading);
        restoreWorkspaceSelection(selectionSnapshot, routeId);
        return;
      }

      workspace.hidden = true;
      workspace.replaceChildren();
      originalMain.hidden = false;
      if (restoreFocus) restoreStage1Focus(routeId, requestedFocus);
    } catch (error) {
      currentLanguage = previousLanguage;
      documentRef.documentElement.lang = previousDocumentLanguage;
      try {
        navList.replaceChildren(...previousNavigationNodes);
      } catch (_) {}
      nav.setAttribute("aria-label", uiText("Розділи Accessible Chess", "Accessible Chess sections"));
      navHeading.textContent = previousNavigationHeading;
      currentRouteId = previousRouteId;
      if (typeof global.showStage1Route === "function") {
        try {
          global.showStage1Route(previousRouteId);
        } catch (_) {}
      }
      throw error;
    }
  }

  function refresh(restoreFocus) {
    const bridge = api();
    if (!bridge || typeof bridge.v2_snapshot !== "function") return Promise.resolve();
    return bridge.v2_snapshot().then(function (snapshot) { render(snapshot, !!restoreFocus); });
  }

  function isVersion2DomainAction(actionId) {
    return actionId.indexOf("pgn.") === 0 || actionId.indexOf("library.") === 0 ||
      actionId.indexOf("book.") === 0 || actionId.indexOf("training.") === 0 ||
      actionId.indexOf("teacher.") === 0 || actionId.indexOf("classes.") === 0;
  }

  function delegatedHasOwnPresentationEvent(actionId) {
    return actionId === "library.import" || actionId === "library.cancel_import" ||
      actionId === "library.export";
  }

  function restoreQueuedNativeFocus(id) {
    if (!validFocusId(id)) return false;
    const target = documentRef.getElementById(id);
    if (!target || hiddenByAncestor(target) || typeof target.focus !== "function") return false;
    if (documentRef.activeElement === target) return true;
    const active = documentRef.activeElement;
    if (
      active &&
      (workspace.contains(active) || nav.contains(active)) &&
      !hiddenByAncestor(active)
    ) {
      return true;
    }
    return focusById(id);
  }

  function refreshStage1Surface() {
    if (typeof global.refreshState !== "function") {
      announce(uiText("Не вдалося оновити дошку.", "Could not refresh the board."));
      return Promise.resolve(false);
    }
    return Promise.resolve(global.refreshState()).then(function () {
      return true;
    }, function () {
      announce(uiText("Не вдалося оновити дошку.", "Could not refresh the board."));
      return false;
    });
  }

  function applyQueuedEvent(event, orderedStage1Refreshes) {
    if (!plainObject(event) || !NATIVE_EVENT_KINDS.has(event.kind)) return false;
    if (!plainObject(event.payload)) return false;
    const payload = event.payload;
    if (event.kind === "route" && !validRouteId(payload.route_id)) return false;
    if (event.kind === "delegated" && !validActionId(payload.action_id)) return false;
    if (event.kind === "render-import") {
      if (currentRouteId === "library" && global.AccessibleChessLibrarySurface &&
          typeof global.AccessibleChessLibrarySurface.apply === "function") {
        const selectionSnapshot = captureWorkspaceSelection();
        try {
          global.AccessibleChessLibrarySurface.apply(workspace, event, areaInvoke("library"), announce);
          restoreWorkspaceSelection(selectionSnapshot, currentRouteId);
        } catch (_) {
          restoreWorkspaceSelection(selectionSnapshot, currentRouteId);
          return true;
        }
      } else if (payload.announcement) {
        announce(payload.announcement);
      }
      return false;
    }
    if (event.kind === "delegated") {
      const actionId = typeof payload.action_id === "string" ? payload.action_id : "";
      if (delegatedHasOwnPresentationEvent(actionId)) return false;
      if (actionId && !isVersion2DomainAction(actionId)) {
        orderedStage1Refreshes.push(refreshStage1Surface);
        return false;
      }
    }
    if (event.kind === "book-board") {
      orderedStage1Refreshes.push(refreshStage1Surface);
    }
    if (payload.announcement) announce(payload.announcement);
    if (event.kind === "error" && payload.message) announce(payload.message);
    return event.kind !== "error" && event.kind !== "status";
  }

  let eventDrainInFlight = false;
  let eventDrainPending = false;

  function finishEventDrain() {
    eventDrainInFlight = false;
    if (!eventDrainPending) return;
    eventDrainPending = false;
    drainEvents();
  }

  function drainEvents() {
    if (eventDrainInFlight) {
      eventDrainPending = true;
      return;
    }
    const bridge = api();
    if (!bridge || typeof bridge.v2_drain_events !== "function") return;
    eventDrainInFlight = true;
    eventDrainPending = false;
    let drained;
    try {
      drained = bridge.v2_drain_events();
    } catch (_) {
      finishEventDrain();
      return;
    }
    Promise.resolve(drained).then(function (events) {
      if (!Array.isArray(events) || !events.length || events.length > MAX_NATIVE_EVENT_BATCH) return;
      let needsRefresh = false;
      let queuedTerminalFocus = "";
      const orderedStage1Refreshes = [];
      events.forEach(function (event) {
        const payload = plainObject(event) && plainObject(event.payload) ? event.payload : {};
        if (
          (event.kind === "status" || event.kind === "error") &&
          validFocusId(payload.focus_target)
        ) {
          queuedTerminalFocus = payload.focus_target;
        }
        const refreshRequired = applyQueuedEvent(event, orderedStage1Refreshes);
        if (refreshRequired) needsRefresh = true;
      });
      if (!needsRefresh && !orderedStage1Refreshes.length) {
        if (queuedTerminalFocus) restoreQueuedNativeFocus(queuedTerminalFocus);
        return;
      }
      const repaintBarrier = orderedStage1Refreshes.reduce(function (chain, refreshStage1) {
        return chain.then(function () { return refreshStage1(); });
      }, Promise.resolve());
      return repaintBarrier.then(function () {
        return needsRefresh ? refresh(true) : undefined;
      });
    }).then(finishEventDrain, finishEventDrain);
  }

  documentRef.addEventListener("focusin", function (event) {
    const target = event.target;
    if (!target || !validFocusId(target.id)) return;
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
