(function (global) {
  "use strict";
  if (global.__accessibleChessP0AccessibilityRuntimeInstalled) return;
  global.__accessibleChessP0AccessibilityRuntimeInstalled = true;

  const documentRef = global.document;
  if (!documentRef) return;
  const main = documentRef.getElementById("main-content");
  const workspace = documentRef.getElementById("v2-workspace");
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
    if (workspace && workspace.contains(node)) return workspace;
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

  function nearestSelectionStart(fullText, selectedText, preferredStart) {
    if (!selectedText) return -1;
    let match = fullText.indexOf(selectedText);
    if (match < 0) return -1;
    let best = match;
    let bestDistance = Math.abs(match - preferredStart);
    while (match >= 0) {
      const distance = Math.abs(match - preferredStart);
      if (distance < bestDistance) {
        best = match;
        bestDistance = distance;
      }
      match = fullText.indexOf(selectedText, match + 1);
    }
    return best;
  }

  function captureSemanticSelection() {
    const selection = currentSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount !== 1) return null;
    const range = selection.getRangeAt(0);
    const root = rootForNode(range.startContainer);
    if (!root || rootForNode(range.endContainer) !== root) return null;
    if ((root === workspace && workspace.hidden) || (root === main && main.hidden)) return null;
    try {
      const text = String(range.toString() || "");
      if (!text.trim()) return null;
      const start = textOffset(root, range.startContainer, range.startOffset);
      const end = textOffset(root, range.endContainer, range.endOffset);
      if (end <= start) return null;
      return {
        rootId: root.id,
        route: routeToken(),
        start: start,
        end: end,
        text: text
      };
    } catch (_) {
      return null;
    }
  }

  function restoreSemanticSelection(snapshot) {
    if (!snapshot || snapshot.route !== routeToken()) return false;
    const root = documentRef.getElementById(snapshot.rootId);
    if (!root || root.hidden) return false;
    const selection = currentSelection();
    if (!selection) return false;
    try {
      const fullText = String(root.textContent || "");
      let start = Math.max(0, Math.min(Number(snapshot.start) || 0, fullText.length));
      let end = Math.max(start, Math.min(Number(snapshot.end) || 0, fullText.length));
      if (fullText.slice(start, end) !== snapshot.text) {
        start = nearestSelectionStart(fullText, snapshot.text, start);
        if (start < 0) return false;
        end = Math.min(fullText.length, start + snapshot.text.length);
      }
      const startPoint = textPoint(root, start);
      const endPoint = textPoint(root, end);
      const range = documentRef.createRange();
      range.setStart(startPoint.node, startPoint.offset);
      range.setEnd(endPoint.node, endPoint.offset);
      selection.removeAllRanges();
      selection.addRange(range);
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
      if (!retainedSelection || !mutationTouchesRetainedRoot(records)) return;
      if (retainedSelection.route !== routeToken()) {
        retainedSelection = null;
        return;
      }
      const root = documentRef.getElementById(retainedSelection.rootId);
      if (!root || root.hidden || String(root.textContent || "").indexOf(retainedSelection.text) < 0) {
        retainedSelection = null;
        return;
      }
      restoringSelection = true;
      try {
        if (!restoreSemanticSelection(retainedSelection)) retainedSelection = null;
      } finally {
        restoringSelection = false;
      }
    });
    observer.observe(main, { subtree: true, childList: true, characterData: true });
    if (workspace) observer.observe(workspace, { subtree: true, childList: true, characterData: true });
  }

  let lastAnnouncement = "";
  let lastAnnouncementAt = 0;
  let lastAnnouncementDispatch = 0;
  let dispatchCounter = 0;
  let announcementRunning = false;
  const announcementQueue = [];

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
      }, 35);
    }, 30);
  }

  function exposeAnnouncement(message, dispatchId) {
    if (!message) return false;
    const text = String(message).slice(0, 300);
    const now = Date.now();
    const dispatch = Number(dispatchId) || 0;
    if (text === lastAnnouncement && now - lastAnnouncementAt < 500 && dispatch === lastAnnouncementDispatch) {
      return false;
    }
    lastAnnouncement = text;
    lastAnnouncementAt = now;
    lastAnnouncementDispatch = dispatch;
    announcementQueue.push(text);
    pumpAnnouncements();
    return true;
  }

  global.announce = function (message) {
    return exposeAnnouncement(message, 0);
  };

  if (typeof global.apiAction === "function" && typeof global.render === "function") {
    global.apiAction = async function (name) {
      const args = Array.prototype.slice.call(arguments, 1);
      const dispatchId = ++dispatchCounter;
      try {
        const bridge = global.pywebview && global.pywebview.api;
        if (!bridge || typeof bridge[name] !== "function") throw new Error("action unavailable");
        const result = await bridge[name].apply(bridge, args);
        await global.render(result);
        if (result && result.announcement) exposeAnnouncement(result.announcement, dispatchId);
        return result;
      } catch (_) {
        exposeAnnouncement("Не вдалося виконати дію.", dispatchId);
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
