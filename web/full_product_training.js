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
      renderTrainingSurface(root, payload.snapshot, invoke, announce, payload.focus_target || "");
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

  function appendProgress(host, snapshot) {
    const group = node("section");
    group.setAttribute("aria-label", snapshot.progress_label || "");
    group.appendChild(node("p", snapshot.progress_label || ""));
    group.appendChild(node("p", snapshot.attempts_label || ""));
    group.appendChild(node("p", snapshot.mistakes_label || ""));
    group.appendChild(node("p", snapshot.hints_label || ""));
    host.appendChild(group);
  }

  function appendBoardHost(host, snapshot) {
    const board = snapshot.board && typeof snapshot.board === "object" ? snapshot.board : {};
    if (!board.start_fen) return;
    const boardHost = node("div");
    boardHost.className = "training-position-host";
    boardHost.dataset.fen = String(board.start_fen);
    boardHost.setAttribute("role", "group");
    boardHost.setAttribute("aria-label", board.label || "");
    host.appendChild(boardHost);
  }

  function appendAnswerForm(root, host, snapshot, invoke, announce) {
    if (snapshot.completed) return;
    const form = node("form");
    const label = node("label", snapshot.answer_label || "");
    const input = node("input");
    input.type = "text";
    input.id = "training-answer";
    input.name = "answer";
    input.maxLength = 256;
    input.autocomplete = "off";
    input.spellcheck = false;
    label.htmlFor = input.id;
    const button = node("button", snapshot.submit_label || "");
    button.type = "submit";
    form.appendChild(label);
    form.appendChild(input);
    form.appendChild(button);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      const answer = input.value;
      input.value = "";
      invokeCommand(root, snapshot, invoke, announce, "training.submit", { answer: answer });
    });
    host.appendChild(form);
  }

  function appendActions(root, host, snapshot, invoke, announce) {
    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    (Array.isArray(snapshot.actions) ? snapshot.actions : []).forEach(function (action) {
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

  function appendSolution(host, snapshot) {
    const solution = snapshot.solution && typeof snapshot.solution === "object" ? snapshot.solution : {};
    const moves = Array.isArray(solution.moves) ? solution.moves : [];
    if (!moves.length) return;
    const section = node("section");
    section.appendChild(node("h3", solution.label || ""));
    const list = node("ol");
    moves.forEach(function (move) {
      list.appendChild(node("li", move));
    });
    section.appendChild(list);
    host.appendChild(section);
  }

  function renderTrainingSurface(root, snapshot, invoke, announce, requestedFocus) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("Training root must support replaceChildren");
    }
    requireFunction(invoke, "Training invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Training announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("Training snapshot is required");

    const fragment = document.createDocumentFragment();
    const main = node("section");
    main.id = "training-root";
    main.tabIndex = -1;
    main.appendChild(node("h2", snapshot.heading || ""));
    main.appendChild(node("p", snapshot.description || ""));
    main.appendChild(node("h3", snapshot.title || ""));
    main.appendChild(node("p", snapshot.prompt || ""));
    appendProgress(main, snapshot);
    appendBoardHost(main, snapshot);
    if (snapshot.source && snapshot.source.value) {
      main.appendChild(node("p", String(snapshot.source.label || "") + ": " + String(snapshot.source.value)));
    }
    if (snapshot.message) {
      const message = node("p", snapshot.message);
      message.setAttribute("aria-live", "off");
      main.appendChild(message);
    }
    if (snapshot.completed_message) {
      const completed = node("p", snapshot.completed_message);
      completed.setAttribute("aria-live", "off");
      main.appendChild(completed);
    }
    appendAnswerForm(root, main, snapshot, invoke, announce);
    appendActions(root, main, snapshot, invoke, announce);
    appendSolution(main, snapshot);
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    focusRequested(root, requestedFocus || "");
  }

  global.AccessibleChessTrainingSurface = Object.freeze({ render: renderTrainingSurface });
})(window);
