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
    if (!message) return;
    live.textContent = "";
    global.setTimeout(function () { live.textContent = String(message).slice(0, 300); }, 20);
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

  // Sections 43-44: UI-only layout controls follow the existing semantic
  // navigation, never the product snapshot or native command owner.
  const workspaceLayout = documentRef.createElement("div");
  workspaceLayout.id = "ac43-product-layout";
  workspaceLayout.hidden = true;
  const workspaceLayoutLabel = documentRef.createElement("label");
  workspaceLayoutLabel.htmlFor = "ac43-product-mode";
  const workspaceLayoutMode = documentRef.createElement("select");
  workspaceLayoutMode.id = "ac43-product-mode";
  for (const [value, uk, en] of [
    ["comfortable", "Звичайний вигляд", "Comfortable layout"],
    ["compact", "Компактний вигляд", "Compact layout"],
    ["reading", "Великий текст і читання", "Large text and reading"]
  ]) {
    const choice = documentRef.createElement("option");
    choice.value = value;
    choice.dataset.uk = uk;
    choice.dataset.en = en;
    workspaceLayoutMode.appendChild(choice);
  }
  workspaceLayout.appendChild(workspaceLayoutLabel);
  workspaceLayout.appendChild(workspaceLayoutMode);
  const workspaceCollapse = documentRef.createElement("button");
  workspaceCollapse.type = "button";
  workspaceCollapse.id = "ac43-product-collapse";
  workspaceCollapse.setAttribute("aria-controls", "v2-workspace");
  workspaceLayout.appendChild(workspaceCollapse);
  const workspaceSize = documentRef.createElement("button");
  workspaceSize.type = "button";
  workspaceSize.id = "ac43-product-size";
  workspaceLayout.appendChild(workspaceSize);
  const workspaceReset = documentRef.createElement("button");
  workspaceReset.type = "button";
  workspaceReset.id = "ac43-product-restore";
  workspaceLayout.appendChild(workspaceReset);

  originalMain.parentNode.insertBefore(nav, originalMain);
  originalMain.parentNode.insertBefore(workspaceLayout, originalMain);
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

  // A durable presentation preference per existing route. Fail closed on
  // inaccessible/corrupt storage and never write application/position data.
  const layoutStorageKey = "accessible-chess.product-layout.v1";
  const productModeValues = new Set(["comfortable", "compact", "reading"]);
  function readProductLayouts() {
    try {
      const storage = global.localStorage;
      const source = storage && storage.getItem(layoutStorageKey);
      if (!source || source.length > 1024) return {};
      const parsed = JSON.parse(source);
      if (!parsed || parsed.version !== 1 ||
          !parsed.routes || typeof parsed.routes !== "object" ||
          Array.isArray(parsed.routes)) return {};
      const routes = {};
      for (const route of productRoutes) {
        if (productModeValues.has(parsed.routes[route])) {
          routes[route] = parsed.routes[route];
        }
      }
      return routes;
    } catch (_) {
      return {};
    }
  }
  const productLayouts = readProductLayouts();
  // Route-scoped content panel sizes and collapsed state use the SAME
  // presentation-only Settings key and version; old mode-only values migrate.
  const productPanelSizes = ["auto", "medium", "large"];
  function readProductPanels() {
    try {
      const raw = global.localStorage && global.localStorage.getItem(layoutStorageKey);
      if (!raw || raw.length > 2048) return {};
      const parsed = JSON.parse(raw);
      if (!parsed || parsed.version !== 1 || !parsed.panels ||
          typeof parsed.panels !== "object" || Array.isArray(parsed.panels)) return {};
      const panels = {};
      for (const route of productRoutes) {
        const panel = parsed.panels[route];
        if (panel && typeof panel === "object" && !Array.isArray(panel) &&
            typeof panel.collapsed === "boolean" && productPanelSizes.includes(panel.size)) {
          panels[route] = {collapsed: panel.collapsed, size: panel.size};
        }
      }
      return panels;
    } catch (_) {
      return {};
    }
  }
  const productPanels = readProductPanels();
  let productLayoutDirty = false;
  let productNativeHydrationStarted = false;
  let productNativeWrites = Promise.resolve();
  let productSaveFailureAnnounced = false;
  function productNativeWriteResult(ok) {
    if (ok) { productSaveFailureAnnounced = false; return; }
    if (productSaveFailureAnnounced) return;
    productSaveFailureAnnounced = true;
    announce(uiText(
      "Не вдалося зберегти вигляд розділу в налаштуваннях Windows.",
      "Could not save section layout to Windows settings."
    ));
  }
  function queueNativeProductLayout() {
    const bridge = api();
    if (!bridge || typeof bridge.save_presentation_layout !== "function") return;
    const payload = { version: 1, routes: Object.assign({}, productLayouts),
      panels: Object.assign({}, productPanels) };
    productNativeWrites = productNativeWrites.then(function () {
      return Promise.resolve(bridge.save_presentation_layout("product", payload))
        .then(function (result) { productNativeWriteResult(!!(result && result.ok === true)); });
    }).catch(function () { productNativeWriteResult(false); });
  }
  function persistProductLayouts() {
    productLayoutDirty = true;
    try {
      if (global.localStorage) {
        global.localStorage.setItem(layoutStorageKey, JSON.stringify({
          version: 1, routes: productLayouts, panels: productPanels
        }));
      }
    } catch (_) {}
    queueNativeProductLayout();
  }
  function hydrateNativeProductLayout() {
    if (productNativeHydrationStarted) return;
    const bridge = api();
    if (!bridge || typeof bridge.get_presentation_layout !== "function") return;
    productNativeHydrationStarted = true;
    if (productLayoutDirty) { queueNativeProductLayout(); return; }
    Promise.resolve(bridge.get_presentation_layout("product")).then(function (result) {
      if (productLayoutDirty || !result || result.ok !== true) return;
      const layout = result.layout;
      if (!layout || layout.version !== 1 ||
          !layout.routes || typeof layout.routes !== "object" ||
          Array.isArray(layout.routes)) return;
      for (const route of productRoutes) delete productLayouts[route];
      for (const route of productRoutes) {
        if (productModeValues.has(layout.routes[route])) {
          productLayouts[route] = layout.routes[route];
        }
      }
      for (const route of productRoutes) delete productPanels[route];
      const nativePanels = layout.panels && typeof layout.panels === "object" &&
        !Array.isArray(layout.panels) ? layout.panels : {};
      for (const route of productRoutes) {
        const candidate = nativePanels[route];
        if (candidate && typeof candidate === "object" && !Array.isArray(candidate) &&
            typeof candidate.collapsed === "boolean" &&
            productPanelSizes.includes(candidate.size)) {
          productPanels[route] = {
            collapsed: candidate.collapsed, size: candidate.size
          };
        }
      }
      applyProductLayout(currentRouteId, currentLanguage);
    }).catch(function () {});
  }
  function applyProductLayout(routeId, language) {
    const active = productRoutes.has(routeId);
    workspaceLayout.hidden = !active;
    if (!active) {
      workspace.removeAttribute("data-ac43-presentation");
      workspace.removeAttribute("data-ac43-collapsed");
      workspace.removeAttribute("data-ac43-size");
      return;
    }
    workspaceLayoutLabel.textContent = (language === "en" ? "Workspace layout" : "Вигляд розділу");
    for (const option of workspaceLayoutMode.options) {
      option.textContent = language === "en" ? option.dataset.en : option.dataset.uk;
    }
    const mode = productModeValues.has(productLayouts[routeId])
      ? productLayouts[routeId] : "comfortable";
    workspaceLayoutMode.value = mode;
    workspace.dataset.ac43Presentation = mode;
    const panel = productPanels[routeId] || {collapsed: false, size: "auto"};
    workspace.dataset.ac43Collapsed = panel.collapsed ? "true" : "false";
    workspace.dataset.ac43Size = panel.size;
    workspaceCollapse.setAttribute("aria-expanded", panel.collapsed ? "false" : "true");
    workspaceCollapse.textContent = panel.collapsed
      ? (language === "en" ? "Expand workspace" : "Розгорнути робочу область")
      : (language === "en" ? "Collapse workspace" : "Згорнути робочу область");
    workspaceSize.textContent = (language === "en" ? "Panel height: " : "Висота панелі: ") +
      (panel.size === "large" ? (language === "en" ? "large" : "велика") :
       panel.size === "medium" ? (language === "en" ? "medium" : "середня") :
       (language === "en" ? "auto" : "авто"));
    workspaceReset.textContent = language === "en" ? "Restore workspace" : "Відновити робочу область";
  }
  function currentProductPanel() {
    const panel = productPanels[currentRouteId];
    return panel || {collapsed: false, size: "auto"};
  }
  workspaceCollapse.addEventListener("click", function () {
    if (!productRoutes.has(currentRouteId)) return;
    const panel = currentProductPanel();
    productPanels[currentRouteId] = {collapsed: !panel.collapsed, size: panel.size};
    applyProductLayout(currentRouteId, currentLanguage);
    persistProductLayouts();
    workspaceCollapse.focus({preventScroll:true});
  });
  workspaceSize.addEventListener("click", function () {
    if (!productRoutes.has(currentRouteId)) return;
    const panel = currentProductPanel();
    const next = productPanelSizes[(productPanelSizes.indexOf(panel.size) + 1) % productPanelSizes.length];
    productPanels[currentRouteId] = {collapsed: panel.collapsed, size: next};
    applyProductLayout(currentRouteId, currentLanguage);
    persistProductLayouts();
    workspaceSize.focus({preventScroll:true});
  });
  workspaceReset.addEventListener("click", function () {
    if (!productRoutes.has(currentRouteId)) return;
    delete productLayouts[currentRouteId];
    delete productPanels[currentRouteId];
    applyProductLayout(currentRouteId, currentLanguage);
    persistProductLayouts();
    workspaceReset.focus({preventScroll:true});
  });
  workspaceLayoutMode.addEventListener("change", function () {
    if (!productRoutes.has(currentRouteId)) return;
    const mode = workspaceLayoutMode.value;
    if (!productModeValues.has(mode)) return;
    productLayouts[currentRouteId] = mode;
    workspace.dataset.ac43Presentation = mode;
    persistProductLayouts();
  });

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
        if (items.length && items[0].dom_id) return String(items[0].dom_id);
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
    const items = Array.isArray(snapshot.navigation) ? snapshot.navigation : [];
    const fragment = documentRef.createDocumentFragment();
    items.forEach(function (item) {
      const row = documentRef.createElement("div");
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

    if (restoreFocus) restoreProductFocus(snapshot, routeId, requestedFocus);
  }

  function render(snapshot, restoreFocus) {
    if (!snapshot || typeof snapshot !== "object") return;
    const selectionSnapshot = captureWorkspaceSelection();
    currentLanguage = snapshot.document && snapshot.document.lang === "en" ? "en" : "uk";
    documentRef.documentElement.lang = currentLanguage;
    nav.setAttribute("aria-label", uiText("Розділи Accessible Chess", "Accessible Chess sections"));
    navHeading.textContent = uiText("Розділи", "Sections");
    renderNavigation(snapshot);
    const screen = snapshot.screen && typeof snapshot.screen === "object" ? snapshot.screen : {};
    const routeId = String(screen.route_id || "board");
    currentRouteId = routeId;
    applyProductLayout(routeId, currentLanguage);
    if (typeof global.showStage1Route === "function") global.showStage1Route(routeId);
    const requestedFocus = String(screen.focus_target || "");
    const heading = String(screen.heading || "");

    if (productRoutes.has(routeId)) {
      renderProductSurface(snapshot, routeId, requestedFocus, restoreFocus, heading);
      restoreWorkspaceSelection(selectionSnapshot, routeId);
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
    return actionId.indexOf("pgn.") === 0 || actionId.indexOf("library.") === 0 ||
      actionId.indexOf("book.") === 0 || actionId.indexOf("training.") === 0 ||
      actionId.indexOf("teacher.") === 0 || actionId.indexOf("classes.") === 0;
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
    if (!event || typeof event !== "object") return false;
    const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
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
        refreshStage1Surface();
        return false;
      }
    }
    if (event.kind === "book-board") {
      orderedStage1Refreshes.push(refreshStage1Surface());
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
      const orderedStage1Refreshes = [];
      events.forEach(function (event) {
        const refreshRequired = applyQueuedEvent(event, orderedStage1Refreshes);
        if (!refreshRequired) return;
        needsRefresh = true;
        const payload = event && event.payload && typeof event.payload === "object" ? event.payload : {};
        const candidate = typeof payload.focus_target === "string" ? payload.focus_target : "";
        if (candidate) queuedFocusTarget = candidate;
      });
      if (needsRefresh) {
        const repaintBarrier = orderedStage1Refreshes.length
          ? Promise.all(orderedStage1Refreshes)
          : Promise.resolve();
        repaintBarrier.then(function () {
          return refresh(true);
        }).then(function () {
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

  if (typeof global.addEventListener === "function") {
    global.addEventListener("pywebviewready", hydrateNativeProductLayout);
  }
  hydrateNativeProductLayout();
  refresh(true).catch(function () {
    announce(uiText("Не вдалося завантажити розділи Version 2.", "Could not load Version 2 sections."));
  });
  global.setInterval(drainEvents, 300);
})(window);
