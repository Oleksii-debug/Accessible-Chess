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
  let pendingShellPublicationToken = 0;
  let shellPublicationRequestSequence = 0;
  let pendingShellPublicationRequestId = 0;
  let pendingShellPublicationArea = "";
  let pendingShellPublicationActionId = "";
  let shellRouteTransitionInFlight = false;

  function uiTextFor(language, uk, en) {
    return language === "en" ? en : uk;
  }

  function uiText(uk, en) {
    return uiTextFor(currentLanguage, uk, en);
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
      const training = snapshot.training;
      const answer = training.answer && typeof training.answer === "object"
        ? training.answer
        : {};
      if (answer.disabled !== true) return "training-answer";
      const actions = Array.isArray(training.actions) ? training.actions : [];
      const continueAction = actions.find(function (action) {
        return action && action.command === "training.continue" && action.enabled === true;
      });
      if (continueAction) return "training-action-continue";
      const resetAction = actions.find(function (action) {
        return action && action.command === "training.reset.request" && action.enabled === true;
      });
      return resetAction ? "training-action-reset" : "";
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
    if (focusById(productSurfaceFocusTarget(snapshot, routeId))) return true;
    if (focusById(requestedFocus)) return true;
    return focusById("v2-nav-" + routeId);
  }

  function renderEmptyProduct(routeId, heading, status, language) {
    const title = documentRef.createElement("h2");
    const labels = {
      pgn: "PGN",
      library: uiTextFor(language, "Бібліотека", "Library"),
      books: uiTextFor(language, "Книги", "Books"),
      training: uiTextFor(language, "Тренування", "Training"),
      teacher: uiTextFor(language, "Режим викладача", "Teacher mode"),
      classes: uiTextFor(language, "Класи й учні", "Classes and students")
    };
    title.textContent = heading || labels[routeId] || routeId;
    const message = documentRef.createElement("p");
    message.id = emptyStatusId(routeId);
    message.tabIndex = -1;
    message.setAttribute("role", "status");
    if (status) {
      message.textContent = status;
    } else if (routeId === "pgn") {
      message.textContent = uiTextFor(language, "PGN ще не відкрито.", "No PGN is open yet.");
    } else if (routeId === "library") {
      message.textContent = uiTextFor(
        language,
        "Бібліотека ще не готова до перегляду.",
        "The Library is not ready to browse yet."
      );
    } else if (routeId === "training") {
      message.textContent = uiTextFor(
        language,
        "Відкрийте книгу, перейдіть до блоку «Вправа», а потім відкрийте Тренування.",
        "Open a book, move to an Exercise block, then open Training."
      );
    } else if (routeId === "teacher") {
      message.textContent = uiTextFor(
        language,
        "Немає активного заняття. Режим викладача стане доступним після відкриття канонічного заняття.",
        "No teaching session is active. Teacher mode becomes available after a canonical session is opened."
      );
    } else if (routeId === "classes") {
      message.textContent = uiTextFor(
        language,
        "Дані класів недоступні. Існуючий файл не буде перезаписано автоматично.",
        "Classes data is unavailable. Existing data will not be overwritten automatically."
      );
    } else {
      message.textContent = uiTextFor(language, "Книгу ще не відкрито.", "No book is open yet.");
    }
    workspace.replaceChildren(title, message);
  }

  function areaInvoke(area) {
    return function (command, payload) {
      const bridge = api();
      if (!bridge || typeof bridge.v2_browser_command !== "function") {
        return Promise.reject(new Error("V2 bridge unavailable"));
      }
      if (area === "library" && command === "library.open_game") {
        const openPayload = payload == null ? {} : payload;
        if (!plainObject(openPayload) || Object.keys(openPayload).length !== 0) {
          return Promise.reject(new Error("invalid Library Open payload"));
        }
        return runPublishedBrowserTransition(
          bridge,
          "library",
          command,
          uiText("Не вдалося відкрити партію.", "Could not open the game."),
          false
        );
      }
      return bridge.v2_browser_command(area, command, payload || {});
    };
  }

  function shellPublicationToken(result) {
    if (!plainObject(result) ||
        (result.kind !== "route" && result.kind !== "delegated") ||
        !plainObject(result.payload)) {
      return 0;
    }
    const token = result.payload.publication_token;
    return Number.isSafeInteger(token) && token > 0 ? token : 0;
  }

  function nextShellPublicationRequestId() {
    if (shellPublicationRequestSequence >= Number.MAX_SAFE_INTEGER - 1) return 0;
    shellPublicationRequestSequence += 1;
    return shellPublicationRequestSequence;
  }

  function clearPendingShellPublicationStart(requestId) {
    if (pendingShellPublicationRequestId !== requestId) return;
    pendingShellPublicationRequestId = 0;
    pendingShellPublicationArea = "";
    pendingShellPublicationActionId = "";
  }

  function startShellPublication(bridge, area, actionId, requestId) {
    function attempt() {
      return bridge.v2_browser_command(
        area,
        actionId,
        { publication_protocol: "ack-v1", request_id: requestId }
      ).then(function (result) {
        if (plainObject(result) && result.kind === "error") return result;
        if (!shellPublicationToken(result)) {
          throw new TypeError("invalid shell publication start");
        }
        return result;
      });
    }

    return attempt().catch(function () { return attempt(); });
  }

  function finishShellPublication(bridge, command, token) {
    const expectedKind =
      command === "shell.presentation_commit"
        ? "presentation-commit"
        : "presentation-rollback";

    function publicationFailure(hostResponded, cause) {
      // Normalize every failure into an internal passive record. Promise
      // rejection values and malformed bridge responses are untrusted: they
      // may be frozen/sealed objects or Proxies with active property traps.
      return Object.freeze({
        hostResponded: hostResponded === true,
        cause: cause
      });
    }

    function attempt() {
      return bridge.v2_browser_command("shell", command, { token: token }).then(
        function (result) {
          try {
            if (plainObject(result) && result.kind === "error") {
              throw new Error("shell publication acknowledgement rejected");
            }
            if (!plainObject(result) || result.kind !== expectedKind ||
                !plainObject(result.payload) || result.payload.token !== token) {
              throw new Error("invalid shell publication acknowledgement");
            }
            return result;
          } catch (error) {
            // A resolved bridge call is host-response authority even when the
            // payload itself is malformed or has active accessors.
            throw publicationFailure(true, error);
          }
        },
        function (error) {
          // Transport rejection is opaque. Store it only as a cause; never read
          // from or write to the caller-controlled rejection object.
          throw publicationFailure(false, error);
        }
      );
    }

    // The Python boundary is idempotent for the same token/outcome. A single
    // retry therefore closes local bridge response loss without duplicating a
    // route commit or rollback.
    return attempt().catch(function (firstFailure) {
      return attempt().catch(function (secondFailure) {
        if (firstFailure.hostResponded && !secondFailure.hostResponded) {
          // At least one attempt reached Python, so preserve that authority even
          // when the final retry failed only at transport. Re-wrap instead of
          // mutating the opaque second rejection value.
          throw publicationFailure(true, secondFailure.cause);
        }
        throw secondFailure;
      });
    });
  }

  function clearPendingShellPublication(token) {
    if (pendingShellPublicationToken !== token) return;
    pendingShellPublicationToken = 0;
    if (eventDrainPending || deferredNativeEventBatch !== null) {
      eventDrainPending = false;
      global.setTimeout(drainEvents, 0);
    }
  }

  function recoverShellPublication(bridge, token, failedMessage, preservePresentation) {
    return finishShellPublication(
      bridge,
      "shell.presentation_rollback",
      token
    ).then(function () {
      if (preservePresentation) {
        clearPendingShellPublication(token);
        announce(failedMessage);
        return true;
      }
      return refresh(true).then(function () {
        clearPendingShellPublication(token);
        announce(failedMessage);
        return true;
      }, function () {
        announce(failedMessage);
        return false;
      });
    }, function (error) {
      // A host-level rejection proves only that Python answered. It does not
      // prove that Python forgot this token: rollback/commit cleanup can fail
      // internally while the exact publication remains pending and retryable.
      // Read host authority directly and publish only a snapshot that carries no
      // pending token. If a token is still present, keep recovery fenced.
      if (error && error.hostResponded) {
        if (!bridge || typeof bridge.v2_snapshot !== "function") {
          announce(failedMessage);
          return Promise.resolve(false);
        }
        return bridge.v2_snapshot().then(function (snapshot) {
          const hostToken = snapshotShellPublicationToken(snapshot);
          if (hostToken) {
            if (hostToken !== token) pendingShellPublicationToken = hostToken;
            announce(failedMessage);
            return false;
          }
          if (preservePresentation) {
            clearPendingShellPublication(token);
            announce(failedMessage);
            return true;
          }
          try {
            render(snapshot, true);
          } catch (_) {
            announce(failedMessage);
            return false;
          }
          clearPendingShellPublication(token);
          announce(failedMessage);
          return true;
        }, function () {
          announce(failedMessage);
          return false;
        });
      }
      announce(failedMessage);
      return false;
    });
  }

  function recoverPendingShellPublicationStart(bridge, failedMessage) {
    const requestId = pendingShellPublicationRequestId;
    const pendingArea = pendingShellPublicationArea;
    const pendingActionId = pendingShellPublicationActionId;
    if (!requestId || !pendingArea || !pendingActionId) return Promise.resolve(true);
    return startShellPublication(
      bridge,
      pendingArea,
      pendingActionId,
      requestId
    ).then(function (result) {
      if (result && result.kind === "error") {
        clearPendingShellPublicationStart(requestId);
        return true;
      }
      const token = shellPublicationToken(result);
      if (!token) return false;
      clearPendingShellPublicationStart(requestId);
      pendingShellPublicationToken = token;
      return recoverShellPublication(bridge, token, failedMessage);
    }, function () {
      announce(failedMessage);
      return false;
    });
  }

  function recoverOutstandingShellPublication(bridge, failedMessage) {
    function continueAfterKnownToken() {
      return recoverPendingShellPublicationStart(bridge, failedMessage);
    }
    if (!pendingShellPublicationToken) return continueAfterKnownToken();
    const previousToken = pendingShellPublicationToken;
    return recoverShellPublication(
      bridge,
      previousToken,
      failedMessage
    ).then(function (recovered) {
      if (!recovered) return false;
      return continueAfterKnownToken();
    });
  }

  function startPublishedBrowserTransition(
    bridge,
    area,
    actionId,
    failedMessage,
    announceHostError
  ) {
    const requestId = nextShellPublicationRequestId();
    if (!requestId) {
      announce(failedMessage);
      return Promise.resolve(null);
    }
    pendingShellPublicationRequestId = requestId;
    pendingShellPublicationArea = area;
    pendingShellPublicationActionId = actionId;

    return startShellPublication(
      bridge,
      area,
      actionId,
      requestId
    ).then(function (result) {
      if (result && result.kind === "error") {
        clearPendingShellPublicationStart(requestId);
        if (announceHostError && result.payload) {
          announce(result.payload.message || "");
        }
        return result;
      }
      const token = shellPublicationToken(result);
      if (!token) {
        announce(failedMessage);
        return null;
      }
      clearPendingShellPublicationStart(requestId);
      pendingShellPublicationToken = token;

      return refresh(true).then(function () {
        return finishShellPublication(
          bridge,
          "shell.presentation_commit",
          token
        ).then(function () {
          clearPendingShellPublication(token);
          if (
            area === "library" &&
            actionId === "library.open_game" &&
            result.kind === "delegated"
          ) {
            // publication_token is transport authority only. Never leak it into
            // the strict Library delegated-event schema after commit.
            return {
              kind: "delegated",
              payload: { action: "library.open_game" }
            };
          }
          return result;
        }, function () {
          return recoverShellPublication(
            bridge,
            token,
            failedMessage
          ).then(function () { return null; });
        });
      }, function (error) {
        return recoverShellPublication(
          bridge,
          token,
          failedMessage,
          !!(error && error.committedPresentationPreserved === true)
        ).then(function () { return null; });
      });
    }, function () {
      // Keep the exact area/action/request tuple. The host may already have
      // executed the transition and lost both responses; the next interaction
      // must replay this request before doing anything new.
      announce(failedMessage);
      return null;
    });
  }

  function runPublishedBrowserTransition(
    bridge,
    area,
    actionId,
    failedMessage,
    announceHostError
  ) {
    if (shellRouteTransitionInFlight) return Promise.resolve(null);
    shellRouteTransitionInFlight = true;
    return Promise.resolve()
      .then(waitForEventDrainIdle)
      .then(function () {
        return recoverOutstandingShellPublication(bridge, failedMessage);
      })
      .then(function (recovered) {
        if (!recovered) return null;
        return startPublishedBrowserTransition(
          bridge,
          area,
          actionId,
          failedMessage,
          announceHostError
        );
      })
      .then(function (result) {
        finishRouteTransition();
        return result;
      }, function () {
        announce(failedMessage);
        finishRouteTransition();
        return null;
      });
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
        const failedMessage = uiText(
          "Не вдалося відкрити розділ.",
          "Could not open the section."
        );
        runPublishedBrowserTransition(
          bridge,
          "shell",
          actionId,
          failedMessage,
          true
        );
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

  function commitShellChrome(navigationState, language, routeId) {
    currentLanguage = language;
    documentRef.documentElement.lang = language;
    nav.setAttribute(
      "aria-label",
      uiTextFor(language, "Розділи Accessible Chess", "Accessible Chess sections")
    );
    navHeading.textContent = uiTextFor(language, "Розділи", "Sections");
    navList.replaceChildren(navigationState.fragment);
    currentRouteId = routeId;
    if (typeof global.showStage1Route === "function") global.showStage1Route(routeId);
  }

  function deactivateLibrarySurface() {
    const surface = global.AccessibleChessLibrarySurface;
    if (surface && typeof surface.deactivate === "function") {
      surface.deactivate(workspace);
    }
  }

  function renderProductSurface(
    snapshot,
    routeId,
    requestedFocus,
    heading,
    language
  ) {
    const previousWorkspaceNodes = Array.from(
      workspace.childNodes || workspace.children || []
    );
    const previousActiveElement = documentRef.activeElement;

    try {
      if (routeId === "pgn") {
        if (snapshot.pgn && global.AccessibleChessPgnSurface) {
          global.AccessibleChessPgnSurface.render(workspace, snapshot.pgn, areaInvoke("pgn"), announce, requestedFocus || "");
        } else {
          renderEmptyProduct(routeId, heading, "", language);
        }
        return requestedFocus;
      }
      if (routeId === "library") {
        if (snapshot.library && global.AccessibleChessLibrarySurface) {
          global.AccessibleChessLibrarySurface.render(workspace, snapshot.library, areaInvoke("library"), announce, requestedFocus || "");
        } else {
          renderEmptyProduct(routeId, heading, "", language);
        }
        return requestedFocus;
      }
      if (routeId === "books") {
        if (snapshot.books && global.AccessibleChessBookSurface) {
          global.AccessibleChessBookSurface.render(workspace, snapshot.books, areaInvoke("books"), announce, requestedFocus || "");
        } else {
          renderEmptyProduct(routeId, heading, "", language);
        }
        return requestedFocus;
      }
      if (routeId === "training") {
        const focus = requestedFocus === "training-prompt" ? "training-answer" : requestedFocus;
        if (snapshot.training && global.AccessibleChessTrainingSurface) {
          global.AccessibleChessTrainingSurface.render(
            workspace, snapshot.training, areaInvoke("training"), announce, focus || "training-answer"
          );
        } else {
          renderEmptyProduct(routeId, heading, "", language);
        }
        return focus;
      }
      if (routeId === "teacher") {
        if (snapshot.teacher && global.AccessibleChessTeacherSurface) {
          global.AccessibleChessTeacherSurface.render(
            workspace, snapshot.teacher, areaInvoke("teacher"), announce, requestedFocus || ""
          );
        } else {
          renderEmptyProduct(routeId, heading, "", language);
        }
        return requestedFocus;
      }
      if (routeId === "classes") {
        if (snapshot.education && global.AccessibleChessEducationSurface) {
          global.AccessibleChessEducationSurface.render(
            workspace,
            snapshot.education,
            areaInvoke("classes"),
            announce,
            requestedFocus || "",
            uiTextFor(language, "Не вдалося виконати дію з класами.", "Could not complete the Classes action.")
          );
        } else {
          renderEmptyProduct(routeId, heading, "", language);
        }
        return requestedFocus;
      }
      throw new TypeError("unsupported V2 product route");
    } catch (error) {
      try {
        workspace.replaceChildren(...previousWorkspaceNodes);
      } catch (_) {}
      if (
        previousActiveElement &&
        typeof previousActiveElement.focus === "function" &&
        !hiddenByAncestor(previousActiveElement)
      ) {
        try {
          previousActiveElement.focus({ preventScroll: true });
        } catch (_) {}
      }
      throw {
        committedPresentationPreserved: true,
        cause: error
      };
    }
  }

  function render(snapshot, restoreFocus) {
    if (!plainObject(snapshot)) return;
    const selectionSnapshot = captureWorkspaceSelection();
    const nextLanguage =
      snapshot.document && snapshot.document.lang === "en" ? "en" : "uk";
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

    if (productRoutes.has(routeId)) {
      const workspaceWasHidden = workspace.hidden;
      const productFocus = renderProductSurface(
        snapshot,
        routeId,
        requestedFocus,
        heading,
        nextLanguage
      );
      if (routeId !== "library") deactivateLibrarySurface();
      commitShellChrome(navigationState, nextLanguage, routeId);
      originalMain.hidden = true;
      workspace.hidden = false;
      if (restoreFocus || workspaceWasHidden) {
        restoreProductFocus(snapshot, routeId, productFocus);
      }
      restoreWorkspaceSelection(selectionSnapshot, routeId);
      return;
    }

    commitShellChrome(navigationState, nextLanguage, routeId);
    deactivateLibrarySurface();
    workspace.hidden = true;
    workspace.replaceChildren();
    originalMain.hidden = false;
    if (restoreFocus) restoreStage1Focus(routeId, requestedFocus);
  }

  function snapshotShellPublicationToken(snapshot) {
    if (!plainObject(snapshot)) return 0;
    const token = snapshot.shell_publication_token;
    return Number.isSafeInteger(token) && token > 0 ? token : 0;
  }

  function refresh(restoreFocus) {
    const bridge = api();
    if (!bridge || typeof bridge.v2_snapshot !== "function") return Promise.resolve();
    return bridge.v2_snapshot().then(function (snapshot) {
      const orphanedToken = snapshotShellPublicationToken(snapshot);
      if (
        orphanedToken &&
        !pendingShellPublicationToken &&
        !pendingShellPublicationRequestId
      ) {
        // A WebView reload can erase the browser's request/token memory after
        // Python already acquired the publication hold. Never render that
        // unacknowledged candidate as committed state. Recover through the same
        // idempotent rollback protocol, then read one canonical snapshot.
        pendingShellPublicationToken = orphanedToken;
        return recoverShellPublication(
          bridge,
          orphanedToken,
          uiText(
            "Відновлено попередній розділ після перезапуску подання.",
            "Restored the previous section after the view restarted."
          )
        ).then(function (recovered) {
          if (!recovered) {
            throw new Error("orphaned shell publication recovery is still pending");
          }
        });
      }
      render(snapshot, !!restoreFocus);
    });
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
  let deferredNativeEventBatch = null;
  let eventDrainIdleWaiters = [];

  function validNativeEventForBatch(event) {
    if (!plainObject(event) || !NATIVE_EVENT_KINDS.has(event.kind)) return false;
    if (!plainObject(event.payload)) return false;
    if (event.kind === "route" && !validRouteId(event.payload.route_id)) return false;
    if (event.kind === "delegated" && !validActionId(event.payload.action_id)) return false;
    return true;
  }

  function validNativeEventBatch(events) {
    if (!Array.isArray(events) || !events.length || events.length > MAX_NATIVE_EVENT_BATCH) {
      return false;
    }
    // Validate the complete bounded batch before the first live-region, focus,
    // Library surface or repaint side effect. A malformed later event must not
    // leave earlier events from the same native transaction partially visible.
    for (let index = 0; index < events.length; index += 1) {
      if (!validNativeEventForBatch(events[index])) return false;
    }
    return true;
  }

  function waitForEventDrainIdle() {
    if (!eventDrainInFlight) return Promise.resolve();
    return new Promise(function (resolve) {
      eventDrainIdleWaiters.push(resolve);
    });
  }

  function browserOwnsPendingShellPublication() {
    return !!pendingShellPublicationToken || !!pendingShellPublicationRequestId;
  }

  function finishRouteTransition() {
    shellRouteTransitionInFlight = false;
    if (
      eventDrainPending &&
      !browserOwnsPendingShellPublication() &&
      !eventDrainInFlight
    ) {
      eventDrainPending = false;
      drainEvents();
    }
  }

  function finishEventDrain() {
    eventDrainInFlight = false;
    const waiters = eventDrainIdleWaiters;
    eventDrainIdleWaiters = [];
    waiters.forEach(function (resolve) { resolve(); });
    if (shellRouteTransitionInFlight || browserOwnsPendingShellPublication()) return;
    if (!eventDrainPending) return;
    eventDrainPending = false;
    drainEvents();
  }

  function drainEvents() {
    if (shellRouteTransitionInFlight || browserOwnsPendingShellPublication()) {
      eventDrainPending = true;
      return;
    }
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
      if (deferredNativeEventBatch !== null) {
        drained = deferredNativeEventBatch;
        deferredNativeEventBatch = null;
      } else {
        drained = bridge.v2_drain_events();
      }
    } catch (_) {
      finishEventDrain();
      return;
    }
    Promise.resolve(drained).then(function (events) {
      if (!validNativeEventBatch(events)) return;
      if (browserOwnsPendingShellPublication()) {
        // A route-start response may be lost after Python acquired its hold but
        // before this browser learned the token. Treat the retained request_id
        // as the same publication fence so a previously started native-event
        // drain cannot publish stale UI while route authority is unresolved.
        deferredNativeEventBatch = events;
        eventDrainPending = true;
        return;
      }
      let needsRefresh = false;
      let queuedTerminalFocus = "";
      const orderedStage1Refreshes = [];
      events.forEach(function (event) {
        if (
          plainObject(event) &&
          (event.kind === "status" || event.kind === "error") &&
          plainObject(event.payload) &&
          validFocusId(event.payload.focus_target)
        ) {
          queuedTerminalFocus = event.payload.focus_target;
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
        // A repaint owns focus through refresh(true). Raw terminal focus is used
        // only in the no-repaint path above, so one event can never produce two
        // competing focus transitions.
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

  // A pywebview "loaded" event can precede the JavaScript bridge.  In that
  // order a one-shot refresh silently resolves without rendering navigation,
  // leaving only the raw Stage 1 HTML visible.  Bootstrap only when the bridge
  // is actually present, including the case where injection happens after ready.
  let initialV2RefreshStarted = false;
  function initializeV2WhenBridgeReady() {
    const bridge = api();
    if (initialV2RefreshStarted || !bridge || typeof bridge.v2_snapshot !== "function") return;
    initialV2RefreshStarted = true;
    refresh(true).catch(function () {
      announce(uiText("Не вдалося завантажити розділи Version 2.", "Could not load Version 2 sections."));
    });
  }
  global.addEventListener("pywebviewready", initializeV2WhenBridgeReady);
  initializeV2WhenBridgeReady();
  global.setInterval(drainEvents, 300);
})(window);
