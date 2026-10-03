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

  function wireToolbarKeyboard(toolbar) {
    if (!toolbar || typeof toolbar.addEventListener !== "function") {
      throw new TypeError("toolbar must support keyboard events");
    }
    const controls = [];
    for (let index = 0; index < toolbar.children.length; index += 1) {
      const control = toolbar.children[index];
      if (!control || control.tagName !== "BUTTON") continue;
      control.tabIndex = -1;
      if (!control.disabled) controls.push(control);
    }
    if (!controls.length) return;

    function setActive(control) {
      controls.forEach(function (candidate) {
        candidate.tabIndex = candidate === control ? 0 : -1;
      });
    }

    setActive(controls[0]);
    controls.forEach(function (control) {
      control.addEventListener("focus", function () {
        setActive(control);
      });
    });

    toolbar.addEventListener("keydown", function (event) {
      const current = controls.indexOf(event.target);
      if (current < 0) return;
      let next = current;
      if (event.key === "ArrowRight") {
        next = (current + 1) % controls.length;
      } else if (event.key === "ArrowLeft") {
        next = (current - 1 + controls.length) % controls.length;
      } else if (event.key === "Home") {
        next = 0;
      } else if (event.key === "End") {
        next = controls.length - 1;
      } else {
        return;
      }
      if (typeof event.preventDefault === "function") event.preventDefault();
      const target = controls[next];
      setActive(target);
      if (typeof target.focus === "function") target.focus({ preventScroll: true });
    });
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

  function announceRejected(root, announce, focusBefore) {
    announce(String(root._pgnErrorMessage || "The action could not be completed."));
    if (focusBefore && typeof focusBefore.focus === "function") {
      focusBefore.focus({ preventScroll: true });
    }
  }

  function commandFlightIsCurrent(root, token, epoch) {
    return root._pgnCommandFlight === token && root._pgnRenderEpoch === epoch;
  }

  function invokeCommand(root, invoke, announce, command, payload) {
    if (root._pgnCommandFlight) return false;
    const focusBefore = document.activeElement;
    const epoch = root._pgnRenderEpoch;
    const token = {};
    root._pgnCommandFlight = token;
    Promise.resolve()
      .then(function () {
        if (!commandFlightIsCurrent(root, token, epoch)) return null;
        return invoke(command, payload || {});
      })
      .then(
        function (result) {
          if (!commandFlightIsCurrent(root, token, epoch)) return;
          root._pgnCommandFlight = null;
          applyEvent(root, result, invoke, announce);
        },
        function () {
          if (!commandFlightIsCurrent(root, token, epoch)) return;
          root._pgnCommandFlight = null;
          announceRejected(root, announce, focusBefore);
        }
      );
    return true;
  }

  function renderTree(root, host, snapshot, invoke, announce) {
    const game = snapshot.game || {};
    const section = node("section");
    section.appendChild(node("h3", game.tree_heading || ""));
    const tree = node("ul");
    tree.setAttribute("role", "tree");
    tree.setAttribute("aria-label", game.tree_heading || "");

    const items = Array.isArray(snapshot.tree) ? snapshot.tree : [];
    items.forEach(function (item, itemIndex) {
      const level = Number(item.aria_level || 1);
      const nextItem = itemIndex + 1 < items.length ? items[itemIndex + 1] : null;
      const hasVisibleChild = Boolean(
        nextItem && Number(nextItem.aria_level || 1) === level + 1
      );
      const treeItem = node("li");
      treeItem.id = String(item.dom_id || "");
      treeItem.setAttribute("role", "treeitem");
      treeItem.setAttribute("aria-level", String(item.aria_level || 1));
      treeItem.setAttribute("aria-selected", item.selected ? "true" : "false");
      if (hasVisibleChild) treeItem.setAttribute("aria-expanded", "true");
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
        const navigationKey =
          event.key === "ArrowUp"
          || event.key === "ArrowDown"
          || event.key === "ArrowLeft"
          || event.key === "ArrowRight"
          || event.key === "Home"
          || event.key === "End";
        if (!navigationKey) return;

        // A rendered ARIA tree owns its navigation keys even at a boundary.
        // Quiet boundaries must not scroll the page or manufacture a backend
        // LookupError/NVDA error announcement.
        if (typeof event.preventDefault === "function") event.preventDefault();

        if (event.key === "ArrowUp") {
          if (itemIndex > 0) {
            command = "pgn.move";
            payload = { delta: -1 };
          }
        } else if (event.key === "ArrowDown") {
          if (itemIndex + 1 < items.length) {
            command = "pgn.move";
            payload = { delta: 1 };
          }
        } else if (event.key === "ArrowLeft") {
          if (item.has_parent) command = "pgn.parent";
        } else if (event.key === "ArrowRight") {
          if (hasVisibleChild) {
            command = "pgn.select";
            payload = { node_id: nextItem.node_id };
          }
        } else if (event.key === "Home") {
          if (itemIndex > 0 && items[0]) {
            command = "pgn.select";
            payload = { node_id: items[0].node_id };
          }
        } else if (event.key === "End") {
          const lastIndex = items.length - 1;
          if (itemIndex < lastIndex && items[lastIndex]) {
            command = "pgn.select";
            payload = { node_id: items[lastIndex].node_id };
          }
        }
        if (!command) return;
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
      Promise.resolve()
        .then(function () { return invoke("pgn.comment_edit", { text: textarea.value }); })
        .then(
          function (result) {
            applyEvent(root, result, invoke, announce);
            if (!result || result.kind !== "error") closeAndRestore();
          },
          function () { announceRejected(root, announce, textarea); }
        );
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
    toolbar.setAttribute("aria-orientation", "horizontal");
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
    wireToolbarKeyboard(toolbar);
    host.appendChild(toolbar);
  }

  function renderPgnSurface(root, snapshot, invoke, announce, requestedFocus) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("PGN root must support replaceChildren");
    }
    requireFunction(invoke, "PGN invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "PGN announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("PGN snapshot is required");
    root._pgnRenderEpoch = Number(root._pgnRenderEpoch || 0) + 1;
    root._pgnCommandFlight = null;
    root._pgnErrorMessage = typeof snapshot.error_message === "string" && snapshot.error_message
      ? snapshot.error_message.slice(0, 240)
      : "The action could not be completed.";

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
