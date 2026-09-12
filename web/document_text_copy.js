(function (global) {
  "use strict";
  if (global.__accessibleChessDocumentTextCopyInstalled) return;
  global.__accessibleChessDocumentTextCopyInstalled = true;

  const documentRef = global.document;
  const SELECTABLE_STYLE_ID = "accessible-chess-document-copy-style";
  const TOOLS_ID = "document-copy-tools";
  const DIALOG_ID = "document-copy-dialog";
  const TEXT_ID = "document-copy-text";
  const OPEN_ID = "document-copy-open";
  const CLOSE_ID = "document-copy-close";
  const SELECTION_GUARD_FLAG = "__accessibleChessDocumentSelectionGuardInstalled";
  let selectionMutationDepth = 0;

  function isEnglish() {
    return documentRef.documentElement.lang === "en";
  }

  function text(uk, en) {
    return isEnglish() ? en : uk;
  }

  function installSelectableStyle() {
    if (documentRef.getElementById(SELECTABLE_STYLE_ID)) return;
    const style = documentRef.createElement("style");
    style.id = SELECTABLE_STYLE_ID;
    style.textContent = [
      "#main-content, #v2-workspace,",
      "#main-content p, #main-content div, #main-content span, #main-content li,",
      "#main-content h1, #main-content h2, #main-content h3, #main-content pre, #main-content code,",
      "#v2-workspace p, #v2-workspace div, #v2-workspace span, #v2-workspace li,",
      "#v2-workspace h1, #v2-workspace h2, #v2-workspace h3, #v2-workspace pre, #v2-workspace code {",
      "  -webkit-user-select: text !important;",
      "  user-select: text !important;",
      "}",
      "#document-copy-text { width: min(92vw, 70rem); min-height: 20rem; white-space: pre-wrap; }"
    ].join("\n");
    (documentRef.head || documentRef.documentElement).appendChild(style);
  }

  function visibleTextRoot() {
    const workspace = documentRef.getElementById("v2-workspace");
    if (workspace && !workspace.hidden) return workspace;
    return documentRef.getElementById("main-content") || documentRef.body;
  }

  function semanticRoots() {
    const roots = [];
    const workspace = documentRef.getElementById("v2-workspace");
    const main = documentRef.getElementById("main-content");
    if (workspace) roots.push(workspace);
    if (main) roots.push(main);
    return roots;
  }

  function semanticText(root) {
    if (!root) return "";
    return String(root.innerText || root.textContent || "")
      .replace(/\u00a0/g, " ")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function currentSelection() {
    try {
      return global.getSelection && global.getSelection();
    } catch (_) {
      return null;
    }
  }

  function selectedText() {
    const selection = currentSelection();
    return selection ? String(selection.toString() || "") : "";
  }

  function hasMeaningfulSelection() {
    const selection = currentSelection();
    return !!selection && !selection.isCollapsed && selectedText().trim().length > 0;
  }

  function rangeIntersectsNode(range, node) {
    if (!range || !node) return false;
    try {
      if (typeof range.intersectsNode === "function") return range.intersectsNode(node);
    } catch (_) {}
    try {
      return node.contains(range.startContainer) || node.contains(range.endContainer);
    } catch (_) {
      return false;
    }
  }

  function selectionTouches(node) {
    if (!node) return false;
    const selection = currentSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return false;
    for (let index = 0; index < selection.rangeCount; index += 1) {
      if (rangeIntersectsNode(selection.getRangeAt(index), node)) return true;
    }
    return false;
  }

  function selectionRoot(range) {
    if (!range) return null;
    const roots = semanticRoots();
    for (let index = 0; index < roots.length; index += 1) {
      const root = roots[index];
      try {
        if (root.contains(range.startContainer) && root.contains(range.endContainer)) return root;
      } catch (_) {}
    }
    return null;
  }

  function textOffset(root, container, offset) {
    const probe = documentRef.createRange();
    probe.selectNodeContents(root);
    probe.setEnd(container, offset);
    return probe.toString().length;
  }

  function captureSelectionForMutation(node) {
    if (!node || selectionMutationDepth) return null;
    const selection = currentSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return null;
    const range = selection.getRangeAt(0);
    if (!rangeIntersectsNode(range, node)) return null;
    const root = selectionRoot(range);
    if (!root) return null;
    try {
      const start = textOffset(root, range.startContainer, range.startOffset);
      const end = textOffset(root, range.endContainer, range.endOffset);
      const chosen = String(range.toString() || "");
      if (!chosen.trim() || end <= start) return null;
      return {root: root, start: start, end: end, text: chosen};
    } catch (_) {
      return null;
    }
  }

  function locateTextOffset(root, targetOffset) {
    const showText = global.NodeFilter ? global.NodeFilter.SHOW_TEXT : 4;
    const walker = documentRef.createTreeWalker(root, showText);
    let remaining = Math.max(0, Number(targetOffset) || 0);
    let last = null;
    while (walker.nextNode()) {
      const node = walker.currentNode;
      last = node;
      const length = String(node.data || "").length;
      if (remaining <= length) return {node: node, offset: remaining};
      remaining -= length;
    }
    if (last) return {node: last, offset: String(last.data || "").length};
    return {node: root, offset: 0};
  }

  function nearestSelectedTextOffset(root, expectedText, preferredStart) {
    const allText = String(root.textContent || "");
    if (!expectedText) return preferredStart;
    let index = allText.indexOf(expectedText);
    if (index < 0) return preferredStart;
    let best = index;
    let bestDistance = Math.abs(index - preferredStart);
    while (index >= 0) {
      const distance = Math.abs(index - preferredStart);
      if (distance < bestDistance) {
        best = index;
        bestDistance = distance;
      }
      index = allText.indexOf(expectedText, index + 1);
    }
    return best;
  }

  function restoreSelection(snapshot) {
    if (!snapshot || !snapshot.root || !snapshot.root.isConnected) return false;
    const selection = currentSelection();
    if (!selection) return false;
    try {
      const root = snapshot.root;
      const rootText = String(root.textContent || "");
      let start = Math.max(0, Math.min(snapshot.start, rootText.length));
      let end = Math.max(start, Math.min(snapshot.end, rootText.length));
      if (snapshot.text && rootText.slice(start, end) !== snapshot.text) {
        start = nearestSelectedTextOffset(root, snapshot.text, start);
        end = Math.min(rootText.length, start + snapshot.text.length);
      }
      const startPoint = locateTextOffset(root, start);
      const endPoint = locateTextOffset(root, end);
      const range = documentRef.createRange();
      range.setStart(startPoint.node, startPoint.offset);
      range.setEnd(endPoint.node, endPoint.offset);
      selectionMutationDepth += 1;
      selection.removeAllRanges();
      selection.addRange(range);
      selectionMutationDepth -= 1;
      return String(selection.toString() || "").length > 0;
    } catch (_) {
      selectionMutationDepth = 0;
      return false;
    }
  }

  function installSelectionMutationGuard() {
    if (global[SELECTION_GUARD_FLAG]) return;
    global[SELECTION_GUARD_FLAG] = true;

    const textContentDescriptor = Object.getOwnPropertyDescriptor(global.Node.prototype, "textContent");
    if (textContentDescriptor && textContentDescriptor.get && textContentDescriptor.set && textContentDescriptor.configurable) {
      Object.defineProperty(global.Node.prototype, "textContent", {
        configurable: textContentDescriptor.configurable,
        enumerable: textContentDescriptor.enumerable,
        get: textContentDescriptor.get,
        set: function (value) {
          const snapshot = captureSelectionForMutation(this);
          textContentDescriptor.set.call(this, value);
          if (snapshot) restoreSelection(snapshot);
        }
      });
    }

    const innerHTMLDescriptor = Object.getOwnPropertyDescriptor(global.Element.prototype, "innerHTML");
    if (innerHTMLDescriptor && innerHTMLDescriptor.get && innerHTMLDescriptor.set && innerHTMLDescriptor.configurable) {
      Object.defineProperty(global.Element.prototype, "innerHTML", {
        configurable: innerHTMLDescriptor.configurable,
        enumerable: innerHTMLDescriptor.enumerable,
        get: innerHTMLDescriptor.get,
        set: function (value) {
          const snapshot = captureSelectionForMutation(this);
          innerHTMLDescriptor.set.call(this, value);
          if (snapshot) restoreSelection(snapshot);
        }
      });
    }

    const nativeReplaceChildren = global.Element.prototype.replaceChildren;
    if (typeof nativeReplaceChildren === "function") {
      global.Element.prototype.replaceChildren = function () {
        const snapshot = captureSelectionForMutation(this);
        const result = nativeReplaceChildren.apply(this, arguments);
        if (snapshot) restoreSelection(snapshot);
        return result;
      };
    }

    if (documentRef.body) documentRef.body.dataset.semanticDocumentSelectionGuardReady = "true";
  }

  function buildTools() {
    if (documentRef.getElementById(TOOLS_ID)) return;
    const anchor = documentRef.getElementById("main-content") || documentRef.body.firstChild;

    const tools = documentRef.createElement("div");
    tools.id = TOOLS_ID;
    tools.setAttribute("role", "group");
    tools.setAttribute("aria-label", text("Копіювання тексту", "Text copying"));

    const open = documentRef.createElement("button");
    open.id = OPEN_ID;
    open.type = "button";
    open.textContent = text(
      "Текст поточного розділу для копіювання",
      "Current section text for copying"
    );
    tools.appendChild(open);

    const dialog = documentRef.createElement("dialog");
    dialog.id = DIALOG_ID;
    dialog.setAttribute("aria-labelledby", "document-copy-heading");

    const heading = documentRef.createElement("h2");
    heading.id = "document-copy-heading";
    heading.textContent = text("Текст для копіювання", "Text for copying");
    dialog.appendChild(heading);

    const instructions = documentRef.createElement("p");
    instructions.id = "document-copy-instructions";
    instructions.textContent = text(
      "Це звичайне текстове поле лише для читання. Переміщуйтеся NVDA, виділяйте потрібний фрагмент стандартними командами та натискайте Ctrl+C. Ctrl+A копіює весь поточний розділ.",
      "This is a normal read-only text field. Navigate with your screen reader, select the part you need using standard commands, and press Ctrl+C. Ctrl+A selects the whole current section."
    );
    dialog.appendChild(instructions);

    const textarea = documentRef.createElement("textarea");
    textarea.id = TEXT_ID;
    textarea.readOnly = true;
    textarea.rows = 24;
    textarea.spellcheck = false;
    textarea.setAttribute("aria-describedby", "document-copy-instructions");
    textarea.setAttribute("aria-label", text(
      "Текст поточного розділу для копіювання",
      "Current section text for copying"
    ));
    dialog.appendChild(textarea);

    const close = documentRef.createElement("button");
    close.id = CLOSE_ID;
    close.type = "button";
    close.textContent = text("Закрити", "Close");
    dialog.appendChild(close);

    function refreshLanguage() {
      tools.setAttribute("aria-label", text("Копіювання тексту", "Text copying"));
      open.textContent = text("Текст поточного розділу для копіювання", "Current section text for copying");
      heading.textContent = text("Текст для копіювання", "Text for copying");
      instructions.textContent = text(
        "Це звичайне текстове поле лише для читання. Переміщуйтеся NVDA, виділяйте потрібний фрагмент стандартними командами та натискайте Ctrl+C. Ctrl+A копіює весь поточний розділ.",
        "This is a normal read-only text field. Navigate with your screen reader, select the part you need using standard commands, and press Ctrl+C. Ctrl+A selects the whole current section."
      );
      textarea.setAttribute("aria-label", text(
        "Текст поточного розділу для копіювання",
        "Current section text for copying"
      ));
      close.textContent = text("Закрити", "Close");
    }

    open.addEventListener("click", function () {
      refreshLanguage();
      textarea.value = semanticText(visibleTextRoot());
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      textarea.focus();
      textarea.setSelectionRange(0, 0);
    });

    close.addEventListener("click", function () {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      open.focus();
    });

    dialog.addEventListener("cancel", function () {
      global.setTimeout(function () { open.focus(); }, 0);
    });

    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(tools, anchor);
    else documentRef.body.insertBefore(tools, documentRef.body.firstChild);
    tools.appendChild(dialog);
  }

  function install() {
    installSelectableStyle();
    installSelectionMutationGuard();
    buildTools();
    if (documentRef.body) {
      documentRef.body.dataset.semanticDocumentCopyReady = "true";
      documentRef.body.dataset.semanticDocumentNativeCopy = "preserved";
    }
  }

  global.AccessibleChessDocumentTextCopy = Object.freeze({
    install: install,
    selectedText: selectedText,
    hasMeaningfulSelection: hasMeaningfulSelection,
    selectionTouches: selectionTouches,
    currentSectionText: function () { return semanticText(visibleTextRoot()); }
  });

  if (documentRef.readyState === "loading") {
    documentRef.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})(window);
