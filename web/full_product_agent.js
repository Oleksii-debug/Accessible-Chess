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
    if (!targetId) return false;
    const candidates = root.querySelectorAll("[id]");
    for (let index = 0; index < candidates.length; index += 1) {
      if (candidates[index].id === targetId && typeof candidates[index].focus === "function") {
        candidates[index].focus({ preventScroll: true });
        return true;
      }
    }
    return false;
  }

  function safeInvoke(invoke, command, payload, onResult, onFailure) {
    Promise.resolve(invoke(command, payload || {})).then(onResult).catch(onFailure);
  }

  function transcriptRows(snapshot) {
    return Array.isArray(snapshot.transcript) ? snapshot.transcript : [];
  }

  function syncTranscript(root, snapshot) {
    const list = root.querySelector("#agent-transcript-list");
    const empty = root.querySelector("#agent-transcript-empty");
    if (!list || !empty) return;
    const rows = transcriptRows(snapshot);
    empty.hidden = rows.length !== 0;

    const retained = Object.create(null);
    rows.forEach(function (turn) {
      if (!turn || typeof turn !== "object") return;
      const turnId = String(turn.id || "");
      if (/^agent-turn-[1-9][0-9]*$/.test(turnId)) retained[turnId] = true;
    });
    Array.from(list.children || []).forEach(function (item) {
      if (item && item.id && !retained[item.id] && typeof list.removeChild === "function") {
        list.removeChild(item);
      }
    });

    rows.forEach(function (turn) {
      if (!turn || typeof turn !== "object") return;
      const turnId = String(turn.id || "");
      if (!/^agent-turn-[1-9][0-9]*$/.test(turnId)) return;
      if (root.querySelector("#" + turnId)) return;
      const item = node("li");
      item.id = turnId;
      item.setAttribute("data-role", String(turn.role || ""));
      const article = node("article");
      const heading = node("h4", turn.label || turn.role || "");
      const body = node("p", turn.text || "");
      body.style.whiteSpace = "pre-wrap";
      body.setAttribute("aria-live", "off");
      article.appendChild(heading);
      article.appendChild(body);
      item.appendChild(article);
      list.appendChild(item);
    });
  }

  function applyStatus(root, snapshot) {
    if (!root || !snapshot || typeof snapshot !== "object") return;
    const status = root.querySelector("#agent-live-status");
    const details = root.querySelector("#agent-status-details");
    const input = root.querySelector("#agent-input");
    const send = root.querySelector("#agent-send");
    const stop = root.querySelector("#agent-stop");
    const liveText = String(snapshot.live_status || "");
    const detailText = String(snapshot.status_text || "");
    if (status && status.textContent !== liveText) status.textContent = liveText;
    if (details && details.textContent !== detailText) details.textContent = detailText;
    if (input) {
      input.disabled = snapshot.available === false;
      if (typeof snapshot.input_placeholder === "string") input.placeholder = snapshot.input_placeholder;
      input.maxLength = 8000;
    }
    if (send) send.disabled = snapshot.can_submit !== true;
    if (stop) stop.disabled = snapshot.can_cancel !== true;
    root._agentState = String(snapshot.state || "idle");
  }

  function applySnapshot(root, snapshot) {
    applyStatus(root, snapshot);
    syncTranscript(root, snapshot);
  }

  function schedulePoll(root, invoke, announce) {
    if (!root || (root._agentState !== "running" && root._agentState !== "cancelling")) return;
    const setTimer = global.setTimeout;
    if (typeof setTimer !== "function") return;
    const token = (root._agentPollToken || 0) + 1;
    root._agentPollToken = token;

    function pollFailure() {
      // Background status polling is best-effort. Do not inject an
      // unlocalized or repetitive live-region error; explicit commands still
      // surface their localized failure through the canonical bridge.
    }

    function refreshCompletedTranscript() {
      safeInvoke(invoke, "agent.snapshot", {}, function (result) {
        if (root._agentPollToken !== token) return;
        const payload = result && result.payload && typeof result.payload === "object" ? result.payload : {};
        if (payload.snapshot) applySnapshot(root, payload.snapshot);
      }, pollFailure);
    }

    setTimer(function poll() {
      if (root._agentPollToken !== token) return;
      safeInvoke(invoke, "agent.status", {}, function (result) {
        if (root._agentPollToken !== token) return;
        const payload = result && result.payload && typeof result.payload === "object" ? result.payload : {};
        if (payload.snapshot) applyStatus(root, payload.snapshot);
        if (root._agentState === "running" || root._agentState === "cancelling") {
          setTimer(poll, 500);
        } else {
          refreshCompletedTranscript();
        }
      }, pollFailure);
    }, 500);
  }

  function handleResult(root, result, invoke, announce, requestedFocus) {
    if (!result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if (payload.snapshot) applySnapshot(root, payload.snapshot);
    if (result.kind === "error" && payload.message) announce(String(payload.message));
    if (payload.focus_target) focusTarget(root, String(payload.focus_target));
    else if (requestedFocus) focusTarget(root, requestedFocus);
    schedulePoll(root, invoke, announce);
  }

  function renderAgentSurface(root, snapshot, invoke, announce, requestedFocus, fallbackMessage) {
    if (!root || typeof root.replaceChildren !== "function") throw new TypeError("Agent root must support replaceChildren");
    requireFunction(invoke, "Agent invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Agent announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("Agent snapshot is required");

    root._agentPollToken = (root._agentPollToken || 0) + 1;
    const fragment = document.createDocumentFragment();
    const section = node("section");
    section.id = "agent-conversation";
    section.appendChild(node("h2", snapshot.heading || "Chess assistant"));
    section.appendChild(node("p", snapshot.description || ""));

    const statusHeading = node("h3", snapshot.status_heading || "Status");
    statusHeading.id = "agent-status-heading";
    section.appendChild(statusHeading);
    const live = node("p", snapshot.live_status || "");
    live.id = "agent-live-status";
    live.setAttribute("role", "status");
    live.setAttribute("aria-live", "polite");
    live.setAttribute("aria-atomic", "true");
    section.appendChild(live);
    const details = node("pre", snapshot.status_text || "");
    details.id = "agent-status-details";
    details.setAttribute("aria-live", "off");
    section.appendChild(details);

    const transcript = node("section");
    transcript.setAttribute("aria-labelledby", "agent-transcript-heading");
    const transcriptHeading = node("h3", snapshot.transcript_heading || "Conversation");
    transcriptHeading.id = "agent-transcript-heading";
    transcript.appendChild(transcriptHeading);
    const empty = node("p", snapshot.empty_transcript || "");
    empty.id = "agent-transcript-empty";
    transcript.appendChild(empty);
    const list = node("ol");
    list.id = "agent-transcript-list";
    transcript.appendChild(list);
    section.appendChild(transcript);

    const form = node("form");
    form.id = "agent-form";
    const label = node("label", snapshot.input_label || "Request");
    label.htmlFor = "agent-input";
    const input = node("textarea");
    input.id = "agent-input";
    input.rows = 4;
    input.maxLength = 8000;
    input.placeholder = String(snapshot.input_placeholder || "");
    input.disabled = snapshot.available === false;
    const send = node("button", snapshot.send_label || "Send");
    send.id = "agent-send";
    send.type = "submit";
    send.disabled = snapshot.can_submit !== true;
    form.appendChild(label);
    form.appendChild(input);
    form.appendChild(send);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      const value = String(input.value || "").trim();
      if (!value || send.disabled) return;
      safeInvoke(invoke, "agent.submit", { text: value }, function (result) {
        if (result && result.kind !== "error") input.value = "";
        handleResult(root, result, invoke, announce, "");
      }, function () {
        announce(String(fallbackMessage || "Agent action failed."));
      });
    });
    section.appendChild(form);

    const stop = node("button", snapshot.stop_label || "Stop");
    stop.id = "agent-stop";
    stop.type = "button";
    stop.disabled = snapshot.can_cancel !== true;
    stop.addEventListener("click", function () {
      if (stop.disabled) return;
      safeInvoke(invoke, "agent.cancel", {}, function (result) {
        handleResult(root, result, invoke, announce, "");
      }, function () {
        announce(String(fallbackMessage || "Agent action failed."));
      });
    });
    section.appendChild(stop);

    fragment.appendChild(section);
    root.replaceChildren(fragment);
    applySnapshot(root, snapshot);
    focusTarget(root, requestedFocus || String(snapshot.focus_target || "agent-input"));
    schedulePoll(root, invoke, announce);
  }

  global.AccessibleChessAgentSurface = Object.freeze({
    render: renderAgentSurface,
    apply: function (root, result, invoke, announce) {
      handleResult(root, result, invoke, announce || function () {}, "");
    }
  });
})(window);
