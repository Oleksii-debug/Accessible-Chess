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
    const candidates = root.querySelectorAll("[id]");
    for (let index = 0; index < candidates.length; index += 1) {
      if (candidates[index].id === targetId && typeof candidates[index].focus === "function") {
        candidates[index].focus({ preventScroll: true });
        return;
      }
    }
  }

  function invokeCommand(root, invoke, announce, command, payload, errorMessage) {
    Promise.resolve(invoke(command, payload || {})).then(function (result) {
      applyEvent(root, result, invoke, announce);
    }).catch(function () {
      if (errorMessage) announce(String(errorMessage));
    });
  }

  function applyEvent(root, result, invoke, announce) {
    if (!result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if (result.kind === "render" && payload.snapshot) {
      renderLibrarySurface(root, payload.snapshot, invoke, announce, payload.focus_target || "");
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
  }

  function field(form, id, spec) {
    const wrapper = node("div");
    const label = node("label", spec.label || "");
    label.htmlFor = id;
    const input = node("input");
    input.id = id;
    input.name = id;
    input.type = "text";
    input.maxLength = 256;
    input.value = spec.value || "";
    wrapper.appendChild(label);
    wrapper.appendChild(input);
    form.appendChild(wrapper);
    return input;
  }

  function renderSearchForm(root, host, snapshot, invoke, announce) {
    const filters = snapshot.filters || {};
    const form = node("form");
    form.setAttribute("role", "search");
    form.appendChild(node("h3", snapshot.search_heading || ""));

    const player = field(form, "library-search-player", filters.player || {});
    const event = field(form, "library-search-event", filters.event || {});
    const eco = field(form, "library-search-eco", filters.eco || {});
    const opening = field(form, "library-search-opening", filters.opening || {});
    const source = field(form, "library-search-source", filters.source_name || {});

    const resultWrap = node("div");
    const resultLabel = node("label", (filters.result || {}).label || "");
    const result = node("select");
    result.id = "library-search-result";
    resultLabel.htmlFor = result.id;
    const options = Array.isArray((filters.result || {}).options) ? filters.result.options : [];
    options.forEach(function (item) {
      const option = node("option", item.label || item.value || "");
      option.value = String(item.value || "");
      option.selected = option.value === String((filters.result || {}).value || "");
      result.appendChild(option);
    });
    resultWrap.appendChild(resultLabel);
    resultWrap.appendChild(result);
    form.appendChild(resultWrap);

    const submit = node("button", filters.submit_label || "");
    submit.type = "submit";
    const reset = node("button", filters.reset_label || "");
    reset.type = "button";
    form.appendChild(submit);
    form.appendChild(reset);

    form.addEventListener("submit", function (eventObject) {
      eventObject.preventDefault();
      invokeCommand(root, invoke, announce, "library.search", {
        player: player.value,
        event: event.value,
        eco: eco.value,
        opening: opening.value,
        result: result.value,
        source_name: source.value
      }, snapshot.action_failed || "");
    });
    reset.addEventListener("click", function () {
      invokeCommand(root, invoke, announce, "library.reset", {}, snapshot.action_failed || "");
    });
    host.appendChild(form);
  }

  function renderResults(root, host, snapshot, invoke, announce) {
    const section = node("section");
    section.appendChild(node("h3", snapshot.results_heading || ""));
    const message = snapshot.message || ((snapshot.status === "empty") ? snapshot.empty_message : "");
    if (message) {
      const status = node("p", message);
      status.setAttribute("aria-live", "off");
      section.appendChild(status);
    }

    const rows = Array.isArray(snapshot.rows) ? snapshot.rows : [];
    const list = node("ul");
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", snapshot.results_heading || "");
    rows.forEach(function (row) {
      const option = node("li");
      option.id = String(row.dom_id || "");
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", row.selected ? "true" : "false");
      option.tabIndex = row.selected ? 0 : -1;
      option.appendChild(node("span", row.label || ""));
      if (row.source) option.appendChild(node("span", " — " + row.source));
      option.addEventListener("click", function () {
        invokeCommand(root, invoke, announce, "library.select", { game_id: row.game_id }, snapshot.action_failed || "");
      });
      option.addEventListener("keydown", function (eventObject) {
        if (eventObject.key === "ArrowUp" || eventObject.key === "ArrowDown") {
          eventObject.preventDefault();
          invokeCommand(root, invoke, announce, "library.move", {
            delta: eventObject.key === "ArrowUp" ? -1 : 1
          }, snapshot.action_failed || "");
        } else if (eventObject.key === "Enter") {
          eventObject.preventDefault();
          invokeCommand(root, invoke, announce, "library.open", {}, snapshot.action_failed || "");
        }
      });
      list.appendChild(option);
    });
    section.appendChild(list);

    const paging = snapshot.paging || {};
    const previous = node("button", paging.previous_label || "");
    previous.type = "button";
    previous.disabled = !paging.has_previous;
    previous.addEventListener("click", function () {
      invokeCommand(root, invoke, announce, "library.previous_page", {}, snapshot.action_failed || "");
    });
    const next = node("button", paging.next_label || "");
    next.type = "button";
    next.disabled = !paging.has_next;
    next.addEventListener("click", function () {
      invokeCommand(root, invoke, announce, "library.next_page", {}, snapshot.action_failed || "");
    });
    section.appendChild(previous);
    section.appendChild(next);
    host.appendChild(section);
  }

  function renderActions(root, host, snapshot, invoke, announce) {
    const actions = Array.isArray(snapshot.actions) ? snapshot.actions : [];
    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    actions.forEach(function (action) {
      const button = node("button", action.label || action.command || "");
      button.type = "button";
      button.disabled = !action.enabled;
      button.addEventListener("click", function () {
        invokeCommand(root, invoke, announce, String(action.command || ""), {}, snapshot.action_failed || "");
      });
      toolbar.appendChild(button);
    });
    host.appendChild(toolbar);
  }

  function renderLibrarySurface(root, snapshot, invoke, announce, requestedFocus) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("Library root must support replaceChildren");
    }
    requireFunction(invoke, "Library invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Library announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("Library snapshot is required");

    const fragment = document.createDocumentFragment();
    const main = node("section");
    main.appendChild(node("h2", snapshot.heading || ""));
    renderSearchForm(root, main, snapshot, invoke, announce);
    renderResults(root, main, snapshot, invoke, announce);
    renderActions(root, main, snapshot, invoke, announce);
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    focusTarget(root, requestedFocus || "");
  }

  global.AccessibleChessLibrarySurface = Object.freeze({ render: renderLibrarySurface });
})(window);
