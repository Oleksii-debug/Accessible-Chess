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

  function focusTarget(root, targetId) {
    if (!targetId) return;
    const items = root.querySelectorAll('[role="treeitem"]');
    for (let index = 0; index < items.length; index += 1) {
      if (items[index].id === targetId && typeof items[index].focus === "function") {
        items[index].focus({ preventScroll: true });
        return;
      }
    }
  }

  function renderTags(host, game) {
    const tags = Array.isArray(game.tags) ? game.tags : [];
    if (!tags.length) return;
    const section = node("section");
    section.appendChild(node("h3", game.tags_heading || ""));
    const list = node("dl");
    tags.forEach(function (entry) {
      list.appendChild(node("dt", entry.name || ""));
      list.appendChild(node("dd", entry.value || ""));
    });
    section.appendChild(list);
    host.appendChild(section);
  }

  function renderWarnings(host, game) {
    const warnings = Array.isArray(game.warnings) ? game.warnings : [];
    if (!warnings.length) return;
    const section = node("section");
    section.setAttribute("aria-live", "off");
    section.appendChild(node("h3", game.warnings_heading || ""));
    const list = node("ul");
    warnings.forEach(function (warning) { list.appendChild(node("li", warning)); });
    section.appendChild(list);
    host.appendChild(section);
  }

  function applyEvent(root, result, invoke, announce) {
    if (!result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if (result.kind === "selection" && payload.snapshot) {
      renderPgnSurface(root, payload.snapshot, invoke, announce, payload.focus_target || "");
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
  }

  function invokeCommand(root, invoke, announce, command, payload) {
    Promise.resolve(invoke(command, payload || {})).then(function (result) {
      applyEvent(root, result, invoke, announce);
    });
  }

  function renderTree(root, host, snapshot, invoke, announce) {
    const game = snapshot.game || {};
    const section = node("section");
    section.appendChild(node("h3", game.tree_heading || ""));
    const tree = node("ul");
    tree.setAttribute("role", "tree");
    tree.setAttribute("aria-label", game.tree_heading || "");

    const items = Array.isArray(snapshot.tree) ? snapshot.tree : [];
    items.forEach(function (item) {
      const treeItem = node("li");
      treeItem.id = String(item.dom_id || "");
      treeItem.setAttribute("role", "treeitem");
      treeItem.setAttribute("aria-level", String(item.aria_level || 1));
      treeItem.setAttribute("aria-selected", item.selected ? "true" : "false");
      treeItem.dataset.kind = String(item.kind || "move");
      treeItem.tabIndex = item.selected ? 0 : -1;
      treeItem.style.paddingInlineStart = Math.max(0, Number(item.aria_level || 1) - 1) + "rem";
      treeItem.appendChild(node("span", item.label || ""));

      const comments = Array.isArray(item.comments) ? item.comments : [];
      if (comments.length) {
        const commentGroup = node("div");
        commentGroup.className = "pgn-comments";
        comments.forEach(function (comment) { commentGroup.appendChild(node("p", comment)); });
        treeItem.appendChild(commentGroup);
      }

      treeItem.addEventListener("click", function () {
        invokeCommand(root, invoke, announce, "pgn.select", { node_id: item.node_id });
      });
      treeItem.addEventListener("keydown", function (event) {
        let command = "";
        let payload = {};
        if (event.key === "ArrowUp") {
          command = "pgn.move";
          payload = { delta: -1 };
        } else if (event.key === "ArrowDown") {
          command = "pgn.move";
          payload = { delta: 1 };
        } else if (event.key === "ArrowLeft" && item.has_parent) {
          command = "pgn.parent";
        }
        if (!command) return;
        event.preventDefault();
        invokeCommand(root, invoke, announce, command, payload);
      });
      tree.appendChild(treeItem);
    });

    section.appendChild(tree);
    host.appendChild(section);
  }

  function buildCommentDialog(root, snapshot, invoke, announce) {
    const editor = snapshot.comment_editor || {};
    const dialog = node("dialog");
    dialog.id = "pgn-comment-dialog";
    const title = node("h2", editor.title || "");
    title.id = "pgn-comment-dialog-title";
    dialog.setAttribute("aria-labelledby", title.id);
    dialog.appendChild(title);

    const label = node("label", editor.label || "");
    const textarea = node("textarea");
    textarea.id = "pgn-comment-text";
    textarea.value = editor.value || "";
    label.htmlFor = textarea.id;
    dialog.appendChild(label);
    dialog.appendChild(textarea);
    if (editor.message) dialog.appendChild(node("p", editor.message));

    const save = node("button", editor.save_label || "");
    save.type = "button";
    save.disabled = !editor.enabled;
    const cancel = node("button", editor.cancel_label || "");
    cancel.type = "button";
    let opener = null;

    function closeAndRestore() {
      if (dialog.open) dialog.close();
      if (opener && typeof opener.focus === "function") opener.focus({ preventScroll: true });
    }

    save.addEventListener("click", function () {
      Promise.resolve(invoke("pgn.comment_edit", { text: textarea.value })).then(function (result) {
        applyEvent(root, result, invoke, announce);
        if (!result || result.kind !== "error") closeAndRestore();
      });
    });
    cancel.addEventListener("click", closeAndRestore);
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      closeAndRestore();
    });
    dialog.appendChild(save);
    dialog.appendChild(cancel);

    return {
      dialog: dialog,
      open: function (button) {
        if (!editor.enabled) return;
        opener = button;
        dialog.showModal();
        textarea.focus();
        textarea.select();
      }
    };
  }

  function renderActions(root, host, snapshot, invoke, announce, commentDialog) {
    const actions = Array.isArray(snapshot.actions) ? snapshot.actions : [];
    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    actions.forEach(function (action) {
      const button = node("button", action.label || action.action || "");
      button.type = "button";
      button.disabled = !action.enabled;
      button.dataset.action = String(action.action || "");
      button.addEventListener("click", function () {
        const command = String(action.action || "");
        if (command === "pgn.comment_edit") {
          commentDialog.open(button);
          return;
        }
        invokeCommand(root, invoke, announce, command, {});
      });
      toolbar.appendChild(button);
    });
    host.appendChild(toolbar);
  }

  function renderPgnSurface(root, snapshot, invoke, announce, requestedFocus) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("PGN root must support replaceChildren");
    }
    requireFunction(invoke, "PGN invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "PGN announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("PGN snapshot is required");

    const fragment = document.createDocumentFragment();
    const main = node("section");
    if (snapshot.status === "empty") {
      main.appendChild(node("p", snapshot.empty_message || ""));
      fragment.appendChild(main);
      root.replaceChildren(fragment);
      return;
    }

    const game = snapshot.game || {};
    main.appendChild(node("h2", game.heading || ""));
    main.appendChild(node("p", game.position_label || ""));
    main.appendChild(node("p", (game.result_label || "") + ": " + (game.result || "")));
    renderTags(main, game);
    renderWarnings(main, game);
    renderTree(root, main, snapshot, invoke, announce);
    const commentDialog = buildCommentDialog(root, snapshot, invoke, announce);
    renderActions(root, main, snapshot, invoke, announce, commentDialog);
    main.appendChild(commentDialog.dialog);
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    focusTarget(root, requestedFocus || "");
  }

  global.AccessibleChessPgnSurface = Object.freeze({ render: renderPgnSurface });
})(window);
