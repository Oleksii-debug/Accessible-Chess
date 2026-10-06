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
  let pendingShellPublicationToken = 0;
  let shellPublicationRequestSequence = 0;
  let pendingShellPublicationRequestId = 0;
  let pendingShellPublicationActionId = "";
  let shellRouteTransitionInFlight = false;
  let eventDrainInFlight = false;
  let eventDrainPending = false;
  let deferredNativeEventBatch = null;
  let eventDrainIdleWaiters = [];
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
    if (routeId === "pgn" || routeId === "library" || routeId === "books" || routeId === "training") {
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
    if (focusById(stage1Focus[routeId] || "")) return true;
    // Stage 1 does not yet own route-local DOM targets for every canonical
    // shell module (notably Teacher/Classes). Never leave keyboard/NVDA focus
    // stale on the previous route: the current navigation button is the safe
    // canonical fallback until that route supplies its own surface target.
    return focusById("v2-nav-" + routeId);
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
    return emptyStatusId(routeId);
  }

  function restoreProductFocus(snapshot, routeId, requestedFocus) {
    const active = documentRef.activeElement;
    if (active && workspace.contains(active)) return true;
    if (focusById(productSurfaceFocusTarget(snapshot, routeId))) return true;
    if (focusById(requestedFocus)) return true;
    return focusById("v2-nav-" + routeId);
  }

  function renderEmptyProduct(routeId, heading, language) {
    const title = documentRef.createElement("h2");
    const fallbackHeading = routeId === "pgn"
      ? "PGN"
      : routeId === "library"
        ? uiTextFor(language, "Бібліотека", "Library")
        : routeId === "training"
          ? uiTextFor(language, "Тренування", "Training")
          : uiTextFor(language, "Книги", "Books");
    title.textContent = boundedText(heading, MAX_SCREEN_HEADING) || fallbackHeading;
    const status = documentRef.createElement("p");
    status.id = emptyStatusId(routeId);
    status.tabIndex = -1;
    status.textContent = routeId === "pgn"
      ? uiTextFor(language, "PGN ще не відкрито.", "No PGN is open yet.")
      : routeId === "library"
        ? uiTextFor(language, "Бібліотека ще не готова до перегляду.", "The Library is not ready to browse yet.")
        : routeId === "training"
          ? uiTextFor(
            language,
            "Відкрийте книгу, перейдіть до блоку «Вправа», а потім відкрийте Тренування.",
            "Open a book, move to an Exercise block, then open Training."
          )
          : uiTextFor(language, "Книгу ще не відкрито.", "No book is open yet.");
    workspace.replaceChildren(title, status);
  }

  function areaInvoke(area) {
    return function (command, payload) {
      const bridge = api();
      if (!bridge || typeof bridge.v2_browser_command !== "function") {
        return Promise.reject(new Error("V2 bridge unavailable"));
      }
      return bridge.v2_browser_command(area, command, payload || {}).then(function (result) {
        // Library Open is a direct browser command whose trusted application
        // handler synchronously changes the canonical shell route to PGN but
        // intentionally queues no second application event. Reuse the one V2
        // snapshot/render/focus authority before resolving the command so the
        // visible/NVDA surface cannot remain on stale Library content.
        if (area === "library" && command === "library.open_game" &&
            result && result.kind !== "error") {
          return refresh(true).then(function () { return result; });
        }
        return result;
      });
    };
  }

  function shellPublicationToken(result) {
    if (!plainObject(result) || result.kind !== "route" || !plainObject(result.payload)) {
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
    pendingShellPublicationActionId = "";
  }

  function startShellPublication(bridge, actionId, requestId) {
    function attempt() {
      return bridge.v2_browser_command(
        "shell",
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

    function hostResponseError(message) {
      const error = new Error(message);
      error.hostResponded = true;
      return error;
    }

    function attempt() {
      return bridge.v2_browser_command("shell", command, { token: token }).then(function (result) {
        if (plainObject(result) && result.kind === "error") {
          throw hostResponseError("shell publication acknowledgement rejected");
        }
        if (!plainObject(result) || result.kind !== expectedKind ||
            !plainObject(result.payload) || result.payload.token !== token) {
          throw hostResponseError("invalid shell publication acknowledgement");
        }
        return result;
      });
    }

    // The Python boundary is idempotent for the same token/outcome. A single
    // retry therefore closes local bridge response loss without duplicating a
    // route commit or rollback.
    return attempt().catch(function (firstError) {
      return attempt().catch(function (secondError) {
        const hostResponded =
          !!(firstError && firstError.hostResponded) ||
          !!(secondError && secondError.hostResponded);
        if (hostResponded && secondError && typeof secondError === "object") {
          secondError.hostResponded = true;
        }
        if (hostResponded && (!secondError || typeof secondError !== "object")) {
          const wrapped = hostResponseError("shell publication acknowledgement rejected");
          wrapped.cause = secondError;
          throw wrapped;
        }
        throw secondError;
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

  function recoverShellPublication(bridge, token, failedMessage) {
    return finishShellPublication(
      bridge,
      "shell.presentation_rollback",
      token
    ).then(function () {
      return refresh(true).then(function () {
        clearPendingShellPublication(token);
        announce(failedMessage);
        return true;
      }, function () {
        announce(failedMessage);
        return false;
      });
    }, function (error) {
      // A host-level rejection means Python definitely answered and the token
      // no longer identifies a rollbackable pending route (normally because a
      // previously uncertain commit actually completed). Re-read canonical
      // authority before allowing another route. A pure transport rejection
      // remains uncertain, so retain the token for the next interaction.
      if (error && error.hostResponded) {
        return refresh(true).then(function () {
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
      if (!item || typeof item !== "object" || Array.isArray(item)) {
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

      const row = documentRef.createElement("li");
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

        function requestRoute() {
          const requestId = nextShellPublicationRequestId();
          if (!requestId) {
            announce(failedMessage);
            return Promise.resolve(false);
          }
          pendingShellPublicationRequestId = requestId;
          pendingShellPublicationActionId = actionId;

          return startShellPublication(
            bridge,
            actionId,
            requestId
          ).then(function (result) {
            if (result && result.kind === "error") {
              clearPendingShellPublicationStart(requestId);
              if (result.payload) announce(result.payload.message || "");
              return false;
            }
            const token = shellPublicationToken(result);
            if (!token) {
              announce(failedMessage);
              return false;
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
                return true;
              }, function () {
                return recoverShellPublication(bridge, token, failedMessage);
              });
            }, function () {
              return recoverShellPublication(bridge, token, failedMessage);
            });
          }, function () {
            announce(failedMessage);
            return false;
          });
        }

        function recoverPendingStart() {
          const requestId = pendingShellPublicationRequestId;
          const pendingActionId = pendingShellPublicationActionId;
          if (!requestId || !pendingActionId) return Promise.resolve(true);
          return startShellPublication(
            bridge,
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

        function continueAfterKnownPublication() {
          return recoverPendingStart().then(function (recovered) {
            if (recovered) return requestRoute();
            return false;
          });
        }

        if (shellRouteTransitionInFlight) return;
        shellRouteTransitionInFlight = true;
        Promise.resolve()
          .then(waitForEventDrainIdle)
          .then(function () {
            if (pendingShellPublicationToken) {
              const previousToken = pendingShellPublicationToken;
              return recoverShellPublication(
                bridge,
                previousToken,
                failedMessage
              ).then(function (recovered) {
                if (recovered) return continueAfterKnownPublication();
                return false;
              });
            }
            return continueAfterKnownPublication();
          })
          .then(finishRouteTransition, function () {
            announce(failedMessage);
            finishRouteTransition();
          });
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
  }

  function renderProductSurface(
    snapshot,
    routeId,
    requestedFocus,
    heading,
    language
  ) {
    if (routeId === "pgn") {
      if (snapshot.pgn && global.AccessibleChessPgnSurface) {
        global.AccessibleChessPgnSurface.render(
          workspace,
          snapshot.pgn,
          areaInvoke("pgn"),
          announce,
          requestedFocus || ""
        );
      } else {
        renderEmptyProduct(routeId, heading, language);
      }
      return requestedFocus;
    }
    if (routeId === "library") {
      if (snapshot.library && global.AccessibleChessLibrarySurface) {
        global.AccessibleChessLibrarySurface.render(
          workspace,
          snapshot.library,
          areaInvoke("library"),
          announce,
          requestedFocus || ""
        );
      } else {
        renderEmptyProduct(routeId, heading, language);
      }
      return requestedFocus;
    }
    if (routeId === "books") {
      if (snapshot.books && global.AccessibleChessBookSurface) {
        global.AccessibleChessBookSurface.render(
          workspace,
          snapshot.books,
          areaInvoke("books"),
          announce,
          requestedFocus || ""
        );
      } else {
        renderEmptyProduct(routeId, heading, language);
      }
      return requestedFocus;
    }
    if (routeId === "training") {
      const focus =
        requestedFocus === "training-prompt"
          ? "training-answer"
          : requestedFocus;
      if (snapshot.training && global.AccessibleChessTrainingSurface) {
        global.AccessibleChessTrainingSurface.render(
          workspace,
          snapshot.training,
          areaInvoke("training"),
          announce,
          focus || "training-answer"
        );
      } else {
        renderEmptyProduct(routeId, heading, language);
      }
      return focus;
    }
    throw new TypeError("unsupported V2 product route");
  }

  function render(snapshot, restoreFocus) {
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return;

    const nextLanguage =
      snapshot.document && snapshot.document.lang === "en" ? "en" : "uk";
    const screen =
      snapshot.screen &&
      typeof snapshot.screen === "object" &&
      !Array.isArray(snapshot.screen)
        ? snapshot.screen
        : {};
    const routeId = screen.route_id;
    const heading = boundedText(screen.heading, MAX_SCREEN_HEADING);
    if (!validRouteId(routeId) || !heading) {
      throw new TypeError("V2 screen schema is invalid");
    }

    // Build and validate the next navigation tree without publishing it.
    // A malformed product snapshot must not advance shell route/aria-current
    // state or hide the currently usable surface.
    const navigationState = renderNavigation(snapshot);
    if (
      !navigationState.routeIds.has(routeId) ||
      navigationState.currentRouteIds.size !== 1 ||
      !navigationState.currentRouteIds.has(routeId)
    ) {
      throw new TypeError("V2 navigation current-route contract is invalid");
    }

    const requestedFocus = validFocusId(screen.focus_target)
      ? screen.focus_target
      : "";

    if (
      routeId === "pgn" ||
      routeId === "library" ||
      routeId === "books" ||
      routeId === "training"
    ) {
      const workspaceWasHidden = workspace.hidden;
      const productFocus = renderProductSurface(
        snapshot,
        routeId,
        requestedFocus,
        heading,
        nextLanguage
      );

      // Only a fully rendered product surface may commit the shell state.
      commitShellChrome(navigationState, nextLanguage, routeId);
      originalMain.hidden = true;
      workspace.hidden = false;

      // If the workspace was hidden during render, a surface-level focus call
      // could not be relied on. Re-establish canonical product focus after the
      // visibility commit even when this refresh was not explicitly a focus
      // restoration request.
      if (restoreFocus || workspaceWasHidden) {
        restoreProductFocus(snapshot, routeId, productFocus);
      }
      return;
    }

    // Stage-1 fallback focus may target the newly committed navigation button,
    // so publish navigation before restoring Stage-1 focus.
    commitShellChrome(navigationState, nextLanguage, routeId);
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
      actionId.indexOf("book.") === 0 || actionId.indexOf("training.") === 0;
  }

  function delegatedHasOwnPresentationEvent(actionId) {
    return actionId === "library.import" || actionId === "library.cancel_import";
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
      const actionId = payload.action_id;
      if (delegatedHasOwnPresentationEvent(actionId)) return false;
      if (actionId === "pgn.open_on_board") {
        orderedStage1Refreshes.push(refreshStage1Surface);
      }
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
      if (!Array.isArray(events) || !events.length || events.length > MAX_NATIVE_EVENT_BATCH) return;
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
      const orderedStage1Refreshes = [];
      events.forEach(function (event) {
        const refreshRequired = applyQueuedEvent(event, orderedStage1Refreshes);
        if (refreshRequired) needsRefresh = true;
      });
      if (!needsRefresh && !orderedStage1Refreshes.length) return;
      const repaintBarrier = orderedStage1Refreshes.reduce(function (chain, refreshStage1) {
        return chain.then(function () { return refreshStage1(); });
      }, Promise.resolve());
      return repaintBarrier.then(function () {
        // refresh(true) is the only focus authority. Native event payloads may
        // request canonical re-rendering, but never apply a second raw DOM
        // focus target after the snapshot has restored focus.
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