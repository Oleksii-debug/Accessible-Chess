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

  function safeInvoke(invoke, command, payload, onResult, announce, fallbackMessage) {
    Promise.resolve(invoke(command, payload || {})).then(onResult).catch(function () {
      if (fallbackMessage) announce(String(fallbackMessage));
    });
  }

  function focusTarget(root, targetId) {
    if (!targetId) return;
    const candidates = root.querySelectorAll("[id]");
    for (let index = 0; index < candidates.length; index += 1) {
      if (candidates[index].id === targetId && typeof candidates[index].focus === "function") {
        candidates[index].focus({ preventScroll: true });
        return;
      }
    }
  }

  function applyEducationEvent(root, result, invoke, announce, fallbackMessage) {
    if (!root || !result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if ((result.kind === "selection" || result.kind === "page") && payload.snapshot) {
      const previous = root.querySelector("#" + String(payload.snapshot.dom_id || ""));
      if (previous && typeof previous.replaceWith === "function") {
        previous.replaceWith(renderSection(payload.snapshot, invoke, announce, fallbackMessage));
      }
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
    focusTarget(root, payload.focus_target || "");
  }

  function invokeSection(invoke, command, payload, root, announce, fallbackMessage) {
    safeInvoke(invoke, command, payload, function (result) {
      applyEducationEvent(root, result, invoke, announce, fallbackMessage);
    }, announce, fallbackMessage);
  }

  function renderSection(section, invoke, announce, fallbackMessage) {
    const wrapper = node("section");
    wrapper.id = String(section.dom_id || "education-section-" + String(section.kind || ""));
    wrapper.setAttribute("data-education-kind", String(section.kind || ""));
    wrapper.appendChild(node("h2", section.heading || ""));

    const rootForEvents = function () { return wrapper.parentNode; };
    const create = section.create_action && typeof section.create_action === "object"
      ? section.create_action : null;
    if (create && create.command) {
      const createButton = node("button", create.label || create.command);
      createButton.type = "button";
      createButton.setAttribute("data-command", String(create.command));
      createButton.addEventListener("click", function () {
        invokeSection(invoke, String(create.command), {}, rootForEvents(), announce, fallbackMessage);
      });
      wrapper.appendChild(createButton);
    }

    const pageControls = node("div");
    const previous = node("button", section.previous_label || "Previous page");
    previous.type = "button";
    previous.disabled = !section.can_previous;
    previous.setAttribute("data-command", "education.page.previous");
    previous.addEventListener("click", function () {
      invokeSection(invoke, "education.page", {
        kind: section.kind,
        direction: -1
      }, rootForEvents(), announce, fallbackMessage);
    });
    pageControls.appendChild(previous);
    const pageStatus = node("span", section.page_label || "");
    pageStatus.setAttribute("aria-live", "off");
    pageControls.appendChild(pageStatus);
    const next = node("button", section.next_label || "Next page");
    next.type = "button";
    next.disabled = !section.can_next;
    next.setAttribute("data-command", "education.page.next");
    next.addEventListener("click", function () {
      invokeSection(invoke, "education.page", {
        kind: section.kind,
        direction: 1
      }, rootForEvents(), announce, fallbackMessage);
    });
    pageControls.appendChild(next);
    wrapper.appendChild(pageControls);

    const items = Array.isArray(section.items) ? section.items : [];
    if (!items.length) {
      wrapper.appendChild(node("p", section.empty_message || ""));
      return wrapper;
    }

    const list = node("ul");
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", section.heading || section.kind || "");
    items.forEach(function (item) {
      const option = node("li");
      option.id = String(item.dom_id || "");
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", item.selected ? "true" : "false");
      option.setAttribute("data-item-key", String(item.item_key || ""));
      option.tabIndex = item.selected ? 0 : -1;
      option.appendChild(node("span", item.label || ""));
      if (item.secondary) {
        option.appendChild(document.createTextNode(" — "));
        option.appendChild(node("span", item.secondary));
      }
      if (item.status) {
        option.appendChild(document.createTextNode(" — "));
        option.appendChild(node("span", item.status));
      }
      option.addEventListener("click", function () {
        invokeSection(invoke, "education.select", {
          kind: section.kind,
          item_key: item.item_key
        }, rootForEvents(), announce, fallbackMessage);
      });
      option.addEventListener("keydown", function (event) {
        let command = "";
        let payload = {};
        if (event.key === "ArrowUp") {
          command = "education.move";
          payload = { kind: section.kind, direction: -1 };
        } else if (event.key === "ArrowDown") {
          command = "education.move";
          payload = { kind: section.kind, direction: 1 };
        } else if (event.key === "Enter" && section.open_enabled) {
          command = "education.open";
          payload = { kind: section.kind };
        }
        if (!command) return;
        event.preventDefault();
        invokeSection(invoke, command, payload, rootForEvents(), announce, fallbackMessage);
      });
      list.appendChild(option);
    });
    wrapper.appendChild(list);

    if (section.open_enabled) {
      const open = node("button", section.open_label || "Open");
      open.type = "button";
      open.setAttribute("data-command", "education.open");
      open.addEventListener("click", function () {
        invokeSection(invoke, "education.open", { kind: section.kind }, rootForEvents(), announce, fallbackMessage);
      });
      wrapper.appendChild(open);
    }
    return wrapper;
  }

  function renderEducationSurface(root, snapshot, invoke, announce, requestedFocus, fallbackMessage) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("education root must support replaceChildren");
    }
    requireFunction(invoke, "education invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "education announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("education snapshot is required");

    const fragment = document.createDocumentFragment();
    const main = node("main");
    const documentState = snapshot.document || {};
    if (documentState.lang) main.setAttribute("lang", String(documentState.lang));
    main.appendChild(node("h1", documentState.heading || ""));
    const sections = Array.isArray(snapshot.sections) ? snapshot.sections : [];
    sections.forEach(function (section) {
      main.appendChild(renderSection(section || {}, invoke, announce, fallbackMessage));
    });
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    focusTarget(root, requestedFocus || "");
  }

  global.AccessibleChessEducationSurface = Object.freeze({
    render: renderEducationSurface,
    apply: applyEducationEvent
  });
})(window);
