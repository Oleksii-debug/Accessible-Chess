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

  function semanticText(root) {
    if (!root) return "";
    return String(root.innerText || root.textContent || "")
      .replace(/\u00a0/g, " ")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function selectedText() {
    try {
      const selection = global.getSelection && global.getSelection();
      return selection ? String(selection.toString() || "") : "";
    } catch (_) {
      return "";
    }
  }

  function hasMeaningfulSelection() {
    return selectedText().trim().length > 0;
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
    currentSectionText: function () { return semanticText(visibleTextRoot()); }
  });

  if (documentRef.readyState === "loading") {
    documentRef.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})(window);
