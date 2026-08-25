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

  function focusRequestedOption(root, focusTarget) {
    if (!focusTarget) return;
    if (focusTarget === "library-search-player") {
      const search = root.querySelector("#library-search-player");
      if (search && typeof search.focus === "function") search.focus({ preventScroll: true });
      return;
    }
    const options = root.querySelectorAll('[role="option"]');
    for (let index = 0; index < options.length; index += 1) {
      if (options[index].id === focusTarget && typeof options[index].focus === "function") {
        options[index].focus({ preventScroll: true });
        return;
      }
    }
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

  function invokeCommand(root, invoke, announce, snapshot, command, payload) {
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

  function appendOptions(select, options, selectedValue) {
    (Array.isArray(options) ? options : []).forEach(function (entry) {
      const option = node("option", entry.label || entry.value || "");
      option.value = String(entry.value || "");
      option.selected = option.value === String(selectedValue || "");
      select.appendChild(option);
    });
  }

  function buildFilterControl(filter) {
    const wrapper = node("div");
    const id = "library-search-" + String(filter.id || "field");
    const label = node("label", filter.label || "");
    label.htmlFor = id;
    let control;
    if (filter.kind === "select") {
      control = node("select");
      appendOptions(control, filter.options, filter.value);
    } else {
      control = node("input");
      control.type = filter.kind === "number" ? "number" : "text";
      control.value = filter.value == null ? "" : String(filter.value);
      if (filter.minimum !== undefined) control.min = String(filter.minimum);
      if (filter.kind !== "number") control.maxLength = 256;
    }
    control.id = id;
    control.name = String(filter.id || "");
    wrapper.appendChild(label);
    wrapper.appendChild(control);
    return { wrapper: wrapper, control: control };
  }

  function renderFilters(root, host, snapshot, invoke, announce) {
    const form = node("form");
    form.setAttribute("aria-label", snapshot.filters_heading || "");
    form.appendChild(node("h3", snapshot.filters_heading || ""));
    const controls = [];
    (Array.isArray(snapshot.filters) ? snapshot.filters : []).forEach(function (filter) {
      const built = buildFilterControl(filter || {});
      controls.push(built.control);
      form.appendChild(built.wrapper);
    });
    const submit = node("button", snapshot.search_label || "");
    submit.type = "submit";
    form.appendChild(submit);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      const payload = {};
      controls.forEach(function (control) {
        payload[control.name] = control.value;
      });
      invokeCommand(root, invoke, announce, snapshot, "library.search", payload);
    });
    host.appendChild(form);
  }

  function renderResults(root, host, snapshot, invoke, announce) {
    const section = node("section");
    section.appendChild(node("h3", snapshot.results_heading || ""));
    const summary = node("p", snapshot.summary || "");
    summary.setAttribute("aria-live", "off");
    section.appendChild(summary);

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
      const label = node("span", row.label || "");
      option.appendChild(label);
      if (row.source_label) {
        const source = node("span", " — " + String(row.source_label));
        source.className = "library-source";
        option.appendChild(source);
      }
      option.addEventListener("click", function () {
        invokeCommand(root, invoke, announce, snapshot, "library.select", { game_id: row.game_id });
      });
      option.addEventListener("keydown", function (event) {
        if (event.key === "ArrowUp" || event.key === "ArrowDown") {
          event.preventDefault();
          invokeCommand(root, invoke, announce, snapshot, "library.move", {
            delta: event.key === "ArrowUp" ? -1 : 1
          });
        } else if (event.key === "Enter") {
          event.preventDefault();
          invokeCommand(root, invoke, announce, snapshot, "library.open_game", {});
        }
      });
      list.appendChild(option);
    });
    section.appendChild(list);
    host.appendChild(section);
  }

  function renderActions(root, host, snapshot, invoke, announce) {
    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    (Array.isArray(snapshot.actions) ? snapshot.actions : []).forEach(function (action) {
      const button = node("button", action.label || action.action || "");
      button.type = "button";
      button.disabled = !action.enabled;
      button.dataset.action = String(action.action || "");
      button.addEventListener("click", function () {
        invokeCommand(root, invoke, announce, snapshot, String(action.action || ""), {});
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
    main.appendChild(node("p", snapshot.description || ""));
    renderFilters(root, main, snapshot, invoke, announce);
    renderResults(root, main, snapshot, invoke, announce);
    renderActions(root, main, snapshot, invoke, announce);
    if (snapshot.message) {
      const message = node("p", snapshot.message);
      message.setAttribute("aria-live", "off");
      main.appendChild(message);
    }
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    focusRequestedOption(root, requestedFocus || "");
  }

  global.AccessibleChessLibrarySurface = Object.freeze({ render: renderLibrarySurface });
})(window);


