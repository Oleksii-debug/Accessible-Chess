(function (global) {
  "use strict";
  if (global.__accessibleChessP0AccessibilityRuntimeInstalled) return;
  global.__accessibleChessP0AccessibilityRuntimeInstalled = true;

  const documentRef = global.document;
  if (!documentRef) return;
  const main = documentRef.getElementById("main-content");
  const workspace = documentRef.getElementById("v2-workspace");
  const navigation = documentRef.getElementById("v2-navigation");
  const live = documentRef.getElementById("live");
  if (!main || !live) return;

  function currentSelection() {
    try {
      return typeof global.getSelection === "function" ? global.getSelection() : null;
    } catch (_) {
      return null;
    }
  }

  function rootForNode(node) {
    if (!node) return null;
    const activeWorkspace = documentRef.getElementById("v2-workspace");
    const activeNavigation = documentRef.getElementById("v2-navigation");
    if (activeWorkspace && activeWorkspace.contains(node)) return activeWorkspace;
    if (activeNavigation && activeNavigation.contains(node)) return activeNavigation;
    if (main.contains(node)) return main;
    return null;
  }

  function routeToken() {
    const current = documentRef.querySelector("#v2-navigation-list [aria-current='page']");
    return current && current.id ? String(current.id) : "stage1";
  }

  function textOffset(root, container, offset) {
    const range = documentRef.createRange();
    range.selectNodeContents(root);
    range.setEnd(container, offset);
    return range.toString().length;
  }

  function textPoint(root, targetOffset) {
    const showText = global.NodeFilter ? global.NodeFilter.SHOW_TEXT : 4;
    const walker = documentRef.createTreeWalker(root, showText);
    let remaining = Math.max(0, Number(targetOffset) || 0);
    let last = null;
    while (walker.nextNode()) {
      const node = walker.currentNode;
      last = node;
      const length = String(node.data || "").length;
      if (remaining <= length) return { node: node, offset: remaining };
      remaining -= length;
    }
    if (last) return { node: last, offset: String(last.data || "").length };
    return { node: root, offset: 0 };
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
    // An old absolute offset is not semantic identity. If two occurrences are
    // equally supported by retained context, guessing can silently move a
    // blind user's copied selection to a different passage after rerender.
    return bestScoreCount === 1 ? best : -1;
  }

  function captureSemanticSelection() {
    const selection = currentSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount !== 1) return null;
    const range = selection.getRangeAt(0);
    const root = rootForNode(range.startContainer);
    if (!root || rootForNode(range.endContainer) !== root) return null;
    if (root.hidden) return null;
    try {
      const text = String(range.toString() || "");
      if (!text.trim()) return null;
      const start = textOffset(root, range.startContainer, range.startOffset);
      const end = textOffset(root, range.endContainer, range.endOffset);
      if (end <= start) return null;
      const context = selectionContext(String(root.textContent || ""), start, end);
      let backward = false;
      if (
        selection.anchorNode &&
        selection.focusNode &&
        rootForNode(selection.anchorNode) === root &&
        rootForNode(selection.focusNode) === root
      ) {
        const anchor = textOffset(root, selection.anchorNode, selection.anchorOffset);
        const focus = textOffset(root, selection.focusNode, selection.focusOffset);
        backward = anchor > focus;
      }
      return {
        rootId: root.id,
        rootNode: root,
        route: routeToken(),
        start: start,
        end: end,
        text: text,
        before: context.before,
        after: context.after,
        backward: backward
      };
    } catch (_) {
      return null;
    }
  }

  function restoreSemanticSelection(snapshot) {
    if (!snapshot || snapshot.route !== routeToken()) return false;
    const root = documentRef.getElementById(snapshot.rootId);
    if (!root || (snapshot.rootNode && root !== snapshot.rootNode) || root.hidden) return false;
    const selection = currentSelection();
    if (!selection) return false;
    try {
      const fullText = String(root.textContent || "");
      let start = Math.max(0, Math.min(Number(snapshot.start) || 0, fullText.length));
      let end = Math.max(start, Math.min(Number(snapshot.end) || 0, fullText.length));
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
      const startPoint = textPoint(root, start);
      const endPoint = textPoint(root, end);
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

  let retainedSelection = null;
  let restoringSelection = false;
  let selectionEpoch = 0;

  function rememberSelection() {
    if (restoringSelection) return;
    const snapshot = captureSemanticSelection();
    if (snapshot) {
      retainedSelection = snapshot;
      selectionEpoch += 1;
      return;
    }
    const epoch = ++selectionEpoch;
    global.setTimeout(function () {
      if (epoch !== selectionEpoch || restoringSelection) return;
      const selection = currentSelection();
      if (!selection || selection.isCollapsed) retainedSelection = null;
    }, 0);
  }

  documentRef.addEventListener("selectionchange", rememberSelection);
  const initial = captureSemanticSelection();
  if (initial) retainedSelection = initial;

  function mutationTouchesRetainedRoot(records) {
    if (!retainedSelection) return false;
    const root = documentRef.getElementById(retainedSelection.rootId);
    if (!root) return false;
    return records.some(function (record) {
      return record.target === root || root.contains(record.target);
    });
  }

  if (typeof global.MutationObserver === "function") {
    const observer = new global.MutationObserver(function (records) {
      if (!retainedSelection) return;
      // Route identity is part of the retained selection authority. A V2
      // transition can be represented entirely by aria-current/hidden
      // attribute changes, so reject stale selection before requiring a
      // content mutation inside the old semantic root.
      if (retainedSelection.route !== routeToken()) {
        retainedSelection = null;
        return;
      }
      const root = documentRef.getElementById(retainedSelection.rootId);
      if (!root || (retainedSelection.rootNode && root !== retainedSelection.rootNode)) {
        retainedSelection = null;
        return;
      }
      if (!mutationTouchesRetainedRoot(records)) return;
      if (root.hidden || String(root.textContent || "").indexOf(retainedSelection.text) < 0) {
        retainedSelection = null;
        return;
      }
      restoringSelection = true;
      try {
        if (!restoreSemanticSelection(retainedSelection)) {
          retainedSelection = null;
        } else {
          // Successful relocation establishes a new canonical browser range.
          // Refresh its bounded semantic context so a later rerender follows
          // that range instead of an obsolete pre-rerender context.
          retainedSelection = captureSemanticSelection();
        }
      } finally {
        restoringSelection = false;
      }
    });
    const observerOptions = {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["hidden", "aria-current"]
    };
    observer.observe(main, observerOptions);
    if (workspace) observer.observe(workspace, observerOptions);
    if (navigation) observer.observe(navigation, observerOptions);
  }

  let lastAnnouncement = "";
  let lastAnnouncementAt = 0;
  let lastAnnouncementDispatch = null;
  let dispatchCounter = 0;
  let announcementRunning = false;
  const announcementQueue = [];
  const rememberedDispatchMessages = new Set();
  const rememberedDispatchMessageOrder = [];
  const recentPassiveAnnouncements = new Map();
  const MAX_REMEMBERED_DISPATCH_MESSAGES = 256;
  const MAX_REMEMBERED_PASSIVE_ANNOUNCEMENTS = 256;
  const SURFACE_EVENT_PREFIX = "\uE000AccessibleChessEvent:";
  const SURFACE_EVENT_SEPARATOR = "\uE001";

  function rememberDispatchMessage(dispatch, text) {
    if (dispatch === null) return false;
    const key = String(dispatch) + "\u0000" + String(text);
    if (rememberedDispatchMessages.has(key)) return true;
    rememberedDispatchMessages.add(key);
    rememberedDispatchMessageOrder.push(key);
    while (rememberedDispatchMessageOrder.length > MAX_REMEMBERED_DISPATCH_MESSAGES) {
      rememberedDispatchMessages.delete(rememberedDispatchMessageOrder.shift());
    }
    return false;
  }

  function rememberPassiveAnnouncement(text, now) {
    const previous = recentPassiveAnnouncements.get(text);
    if (previous !== undefined && now - previous < 500) return true;
    if (recentPassiveAnnouncements.has(text)) recentPassiveAnnouncements.delete(text);
    recentPassiveAnnouncements.set(text, now);
    while (recentPassiveAnnouncements.size > MAX_REMEMBERED_PASSIVE_ANNOUNCEMENTS) {
      recentPassiveAnnouncements.delete(recentPassiveAnnouncements.keys().next().value);
    }
    return false;
  }

  function pumpAnnouncements() {
    if (announcementRunning || !announcementQueue.length) return;
    const text = announcementQueue.shift();
    announcementRunning = true;
    live.setAttribute("aria-busy", "true");
    live.textContent = "";
    global.setTimeout(function () {
      live.textContent = text;
      live.setAttribute("aria-busy", "false");
      global.setTimeout(function () {
        announcementRunning = false;
        pumpAnnouncements();
      }, 20);
    }, 30);
  }

  function exposeAnnouncement(message, dispatchId) {
    if (!message) return false;
    const text = String(message).slice(0, 300);
    const now = Date.now();
    const dispatch = dispatchId === null || dispatchId === undefined ? null : String(dispatchId);
    if (dispatch !== null) {
      if (rememberDispatchMessage(dispatch, text)) return false;
    } else if (rememberPassiveAnnouncement(text, now)) {
      return false;
    }
    lastAnnouncement = text;
    lastAnnouncementAt = now;
    lastAnnouncementDispatch = dispatch;
    announcementQueue.push(text);
    pumpAnnouncements();
    return true;
  }

  global.announce = function (message, eventId) {
    const dispatch = eventId === null || eventId === undefined ? null : "inline:" + String(eventId);
    return exposeAnnouncement(message, dispatch);
  };

  function surfaceResultWillAnnounce(result) {
    if (!result || typeof result !== "object") return false;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    return Boolean(payload.announcement || (result.kind === "error" && payload.message));
  }

  function taggedSurfaceMessage(message, dispatchId) {
    return SURFACE_EVENT_PREFIX + String(dispatchId) + SURFACE_EVENT_SEPARATOR + String(message);
  }

  function decodeSurfaceMessage(message) {
    const text = String(message || "");
    if (!text.startsWith(SURFACE_EVENT_PREFIX)) return null;
    const boundary = text.indexOf(SURFACE_EVENT_SEPARATOR, SURFACE_EVENT_PREFIX.length);
    if (boundary < 0) return null;
    const dispatch = text.slice(SURFACE_EVENT_PREFIX.length, boundary);
    if (!/^surface:\d+$/.test(dispatch)) return null;
    return { dispatch: dispatch, text: text.slice(boundary + SURFACE_EVENT_SEPARATOR.length) };
  }

  function bindSurfaceResultEvent(result, dispatchId) {
    if (!surfaceResultWillAnnounce(result)) return result;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    const taggedPayload = {};
    Object.keys(payload).forEach(function (key) { taggedPayload[key] = payload[key]; });
    if (payload.announcement) {
      taggedPayload.announcement = taggedSurfaceMessage(payload.announcement, dispatchId);
    }
    if (result.kind === "error" && payload.message) {
      taggedPayload.message = taggedSurfaceMessage(payload.message, dispatchId);
    }
    const taggedResult = {};
    Object.keys(result).forEach(function (key) { taggedResult[key] = result[key]; });
    taggedResult.payload = taggedPayload;
    return taggedResult;
  }

  function wrapSurfaceRenderAnnouncement(surfaceName) {
    const surface = global[surfaceName];
    if (!surface || typeof surface !== "object" || typeof surface.render !== "function") return false;
    const replacement = {};
    Object.keys(surface).forEach(function (name) {
      replacement[name] = surface[name];
    });
    const originalRender = surface.render;
    replacement.render = function () {
      const args = Array.prototype.slice.call(arguments);
      if (args.length > 3 && typeof args[2] === "function") {
        const originalInvoke = args[2];
        const originalAnnounce = typeof args[3] === "function" ? args[3] : null;
        const rejectedDispatches = [];

        args[2] = function () {
          const invokeArgs = Array.prototype.slice.call(arguments);
          const dispatchId = "surface:" + String(++dispatchCounter);
          let result;
          try {
            result = originalInvoke.apply(this, invokeArgs);
          } catch (error) {
            rejectedDispatches.push(dispatchId);
            // Always expose the wrapped invoke as a Promise boundary. Some
            // shipping surfaces use Promise.resolve(invoke(...)).catch(...);
            // rethrowing here would escape before their accessible fallback
            // announcement can run.
            return Promise.reject(error);
          }
          return Promise.resolve(result).then(
            function (resolved) {
              return bindSurfaceResultEvent(resolved, dispatchId);
            },
            function (error) {
              rejectedDispatches.push(dispatchId);
              throw error;
            }
          );
        };

        args[3] = function (message) {
          const tagged = decodeSurfaceMessage(message);
          if (tagged) return exposeAnnouncement(tagged.text, tagged.dispatch);
          if (rejectedDispatches.length) {
            return exposeAnnouncement(message, rejectedDispatches.shift());
          }
          if (originalAnnounce) return originalAnnounce(message);
          return exposeAnnouncement(message, null);
        };
      }
      return originalRender.apply(surface, args);
    };
    global[surfaceName] = Object.freeze(replacement);
    return true;
  }

  [
    "AccessibleChessPgnSurface",
    "AccessibleChessLibrarySurface",
    "AccessibleChessBookSurface",
    "AccessibleChessTrainingSurface",
    "AccessibleChessEducationSurface",
    "AccessibleChessTeacherSurface"
  ].forEach(wrapSurfaceRenderAnnouncement);

  if (typeof global.apiAction === "function" && typeof global.render === "function") {
    global.apiAction = async function (name) {
      const args = Array.prototype.slice.call(arguments, 1);
      const dispatchId = "api:" + String(++dispatchCounter);
      try {
        const bridge = global.pywebview && global.pywebview.api;
        if (!bridge || typeof bridge[name] !== "function") throw new Error("action unavailable");
        const result = await bridge[name].apply(bridge, args);
        await global.render(result);
        if (result && result.announcement) exposeAnnouncement(result.announcement, dispatchId);
        return result;
      } catch (_) {
        const genericFailure = documentRef.documentElement && documentRef.documentElement.lang === "en"
          ? "Action could not be completed."
          : "Не вдалося виконати дію.";
        exposeAnnouncement(genericFailure, dispatchId);
        return null;
      }
    };
  }

  global.AccessibleChessP0Runtime = Object.freeze({
    captureSelection: captureSemanticSelection,
    restoreSelection: restoreSemanticSelection,
    nearestSelectionStart: nearestSelectionStart,
    exposeAnnouncement: exposeAnnouncement
  });
})(window);