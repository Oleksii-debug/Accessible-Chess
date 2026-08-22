(function (global) {
  "use strict";

  function requireFunction(value, name) {
    if (typeof value !== "function") throw new TypeError(name + " must be a function");
    return value;
  }

  function node(tag, text) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function focusRequested(root, target) {
    if (!target) return;
    const element = root.querySelector("#" + String(target));
    if (element && typeof element.focus === "function") {
      element.focus({ preventScroll: true });
    }
  }

  function applyEvent(root, result, invoke, announce) {
    if (!result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if (result.kind === "render" && payload.snapshot) {
      renderBookSurface(root, payload.snapshot, invoke, announce, payload.focus_target || "");
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
  }

  function invokeCommand(root, snapshot, invoke, announce, command, payload) {
    const generic = snapshot && snapshot.transport_error_message ? String(snapshot.transport_error_message) : "";
    return Promise.resolve().then(function () {
      return invoke(command, payload || {});
    }).then(function (result) {
      applyEvent(root, result, invoke, announce);
      return result;
    }).catch(function () {
      if (generic) announce(generic);
      return null;
    });
  }

  function appendHeadingPath(host, snapshot, current) {
    const path = Array.isArray(current.heading_path) ? current.heading_path : [];
    if (!path.length) return;
    const nav = node("nav");
    nav.setAttribute("aria-label", snapshot.section_path_label || "");
    const list = node("ol");
    path.forEach(function (label) {
      list.appendChild(node("li", label));
    });
    nav.appendChild(list);
    host.appendChild(nav);
  }

  function appendCurrentBlock(host, snapshot) {
    const current = snapshot.current && typeof snapshot.current === "object" ? snapshot.current : {};
    if (!current.dom_id) return;
    const article = node("article");
    article.id = String(current.dom_id);
    article.tabIndex = -1;
    article.dataset.kind = String(current.kind || "");

    appendHeadingPath(article, snapshot, current);
    article.appendChild(node("p", snapshot.position_label || ""));

    if (current.role === "heading") {
      const level = Number(current.heading_level);
      const tag = level >= 1 && level <= 6 ? "h" + String(level) : "h3";
      article.appendChild(node(tag, current.title || current.text || ""));
    } else if (current.role === "paragraph") {
      article.appendChild(node("p", current.text || ""));
    } else if (current.role === "note") {
      const aside = node("aside", current.text || "");
      article.appendChild(aside);
    } else if (current.role === "img") {
      const figure = node("figure");
      const imageText = node("div", current.text || current.title || "");
      imageText.setAttribute("role", "img");
      imageText.setAttribute("aria-label", current.text || current.title || "");
      figure.appendChild(imageText);
      if (current.title) figure.appendChild(node("figcaption", current.title));
      article.appendChild(figure);
    } else if (current.role === "tree") {
      const tree = node("div", current.text || current.title || "");
      tree.setAttribute("role", "tree");
      article.appendChild(tree);
    } else {
      if (current.title) article.appendChild(node("h3", current.title));
      if (current.text) article.appendChild(node("p", current.text));
    }

    if (current.warning) {
      const warning = node("p", current.warning);
      warning.setAttribute("aria-live", "off");
      article.appendChild(warning);
    }
    if (current.source_anchor) {
      article.appendChild(node("p", (snapshot.source_label || "") + ": " + String(current.source_anchor)));
    }
    if (current.board_position_fen) {
      const board = node("div");
      board.className = "book-position-host";
      board.dataset.fen = String(current.board_position_fen);
      board.setAttribute("role", "group");
      board.setAttribute("aria-label", snapshot.board_label || "");
      article.appendChild(board);
    }
    host.appendChild(article);
  }

  function appendToolbar(root, host, snapshot, invoke, announce) {
    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    (Array.isArray(snapshot.actions) ? snapshot.actions : []).forEach(function (action) {
      if (action.action === "book.bookmark" || action.action === "book.restore_bookmark") return;
      const button = node("button", action.label || action.action || "");
      button.type = "button";
      button.disabled = !action.enabled;
      button.dataset.action = String(action.action || "");
      button.addEventListener("click", function () {
        invokeCommand(root, snapshot, invoke, announce, String(action.action || ""), {});
      });
      toolbar.appendChild(button);
    });
    host.appendChild(toolbar);
  }

  function appendBookmarkForm(root, host, snapshot, invoke, announce) {
    if (snapshot.status !== "ready") return;
    const form = node("form");
    const input = node("input");
    input.type = "text";
    input.id = "book-bookmark-name";
    input.maxLength = 256;
    input.autocomplete = "off";
    const label = node("label", snapshot.bookmark_name_label || "");
    label.htmlFor = input.id;
    form.appendChild(label);
    form.appendChild(input);

    const save = node("button", "");
    const restore = node("button", "");
    save.type = "submit";
    restore.type = "button";
    const actions = Array.isArray(snapshot.actions) ? snapshot.actions : [];
    actions.forEach(function (action) {
      if (action.action === "book.bookmark") save.textContent = String(action.label || "");
      if (action.action === "book.restore_bookmark") restore.textContent = String(action.label || "");
    });
    form.appendChild(save);
    form.appendChild(restore);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      invokeCommand(root, snapshot, invoke, announce, "book.bookmark", { name: input.value });
    });
    restore.addEventListener("click", function () {
      invokeCommand(root, snapshot, invoke, announce, "book.restore_bookmark", { name: input.value });
    });
    host.appendChild(form);
  }

  function renderBookSurface(root, snapshot, invoke, announce, requestedFocus) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("Book root must support replaceChildren");
    }
    requireFunction(invoke, "Book invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Book announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("Book snapshot is required");

    const fragment = document.createDocumentFragment();
    const main = node("section");
    main.id = "book-reader-root";
    main.tabIndex = -1;
    main.appendChild(node("h2", snapshot.heading || ""));
    main.appendChild(node("p", snapshot.description || ""));
    if (snapshot.status === "empty") {
      main.appendChild(node("p", snapshot.empty_message || ""));
    } else {
      appendCurrentBlock(main, snapshot);
      appendToolbar(root, main, snapshot, invoke, announce);
      appendBookmarkForm(root, main, snapshot, invoke, announce);
    }
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    focusRequested(root, requestedFocus || "");
  }

  global.AccessibleChessBookSurface = Object.freeze({ render: renderBookSurface });
})(window);
