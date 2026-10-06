"use strict";

const fs = require("fs");
const vm = require("vm");

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this.style = {};
    this.id = "";
    this.value = "";
    this.textContent = "";
    this.disabled = false;
    this.hidden = false;
    this.placeholder = "";
    this.maxLength = 0;
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index < 0) throw new Error("child not found");
    this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }
  replaceChildren(child) { this.children = []; if (child) this.appendChild(child); }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  getAttribute(name) { return this.attributes[String(name)] || ""; }
  addEventListener(name, listener) { this.listeners[String(name)] = listener; }
  focus() { document.activeElement = this; }
  descendants() { return this.children.flatMap((child) => [child, ...child.descendants()]); }
  querySelector(selector) {
    if (!String(selector).startsWith("#")) return null;
    const id = String(selector).slice(1);
    if (this.id === id) return this;
    return this.descendants().find((item) => item.id === id) || null;
  }
  querySelectorAll(selector) {
    if (selector !== "[id]") return [];
    return [this, ...this.descendants()].filter((item) => item.id);
  }
}

const timers = [];
global.document = {
  activeElement: null,
  createElement: (tagName) => new FakeElement(tagName),
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = { setTimeout: (fn) => { timers.push(fn); return timers.length; } };

const source = fs.readFileSync("web/full_product_agent.js", "utf8");
vm.runInThisContext(source, { filename: "full_product_agent.js" });

function check(condition, message) { if (!condition) throw new Error(message); }
function snapshot(state, turns) {
  const active = state === "running" || state === "cancelling";
  return {
    heading: "Chess assistant",
    description: "Canonical tools only.",
    transcript_heading: "Conversation",
    empty_transcript: "Empty",
    input_label: "Your request",
    input_placeholder: "Ask",
    send_label: "Send",
    stop_label: "Stop",
    status_heading: "Assistant status",
    live_status: state,
    status_text: "State: " + state,
    state: state,
    available: true,
    can_submit: !active,
    can_cancel: active,
    focus_target: active ? "agent-stop" : "agent-input",
    transcript: turns || []
  };
}
async function flush() { await Promise.resolve(); await Promise.resolve(); }

(async function run() {
  const calls = [];
  const announcements = [];
  const invoke = (command, payload) => {
    calls.push([command, payload]);
    if (command === "agent.submit") {
      return {kind:"accepted",payload:{focus_target:"agent-stop",snapshot:snapshot("running",[
        {id:"agent-turn-1",role:"user",label:"You",text:payload.text}
      ])}};
    }
    if (command === "agent.cancel") {
      return {kind:"cancel-requested",payload:{snapshot:snapshot("cancelling",[
        {id:"agent-turn-1",role:"user",label:"You",text:"Analyze e4"}
      ])}};
    }
    if (command === "agent.status") {
      const status = snapshot("completed", []);
      delete status.transcript;
      return {kind:"status",payload:{snapshot:status}};
    }
    if (command === "agent.snapshot") {
      return {kind:"render",payload:{snapshot:snapshot("completed",[
        {id:"agent-turn-1",role:"user",label:"You",text:"Analyze e4"},
        {id:"agent-turn-2",role:"assistant",label:"Assistant",text:"e4 controls the center.\nSecond line remains copyable."}
      ])}};
    }
    throw new Error("unexpected command");
  };

  const root = new FakeElement("div");
  window.AccessibleChessAgentSurface.render(root, snapshot("idle", []), invoke, (m)=>announcements.push(String(m)), "agent-input", "Action failed");
  const input = root.querySelector("#agent-input");
  const send = root.querySelector("#agent-send");
  const stop = root.querySelector("#agent-stop");
  check(document.activeElement === input, "input did not receive initial focus");
  check(send.disabled === false && stop.disabled === true, "idle controls are wrong");
  check(root.querySelector("#agent-live-status").getAttribute("role") === "status", "concise live status missing");
  check(root.querySelector("#agent-status-details").getAttribute("aria-live") === "off", "copyable status must not be a live-region transcript");

  input.value = "Analyze e4";
  let prevented = false;
  root.querySelector("#agent-form").listeners.submit({preventDefault(){prevented=true;}});
  await flush();
  check(prevented, "form submit did not prevent page navigation");
  check(calls[0][0] === "agent.submit" && calls[0][1].text === "Analyze e4", "submit command changed");
  check(input.value === "", "accepted prompt did not clear");
  check(document.activeElement === stop, "running request did not make Stop the focus target");
  check(stop.disabled === false && send.disabled === true, "running controls are wrong");
  const firstTurn = root.querySelector("#agent-turn-1");
  check(Boolean(firstTurn), "user transcript turn missing");
  const firstBody = firstTurn.descendants().find((x)=>x.tagName === "P");
  check(firstBody.textContent === "Analyze e4", "user transcript text changed");
  check(firstBody.getAttribute("aria-live") === "off", "full transcript must not be repeatedly announced");

  check(timers.length >= 1, "running state did not schedule status polling");
  const poll = timers.shift();
  poll();
  await flush();
  check(calls.some((x)=>x[0] === "agent.status"), "active polling retransmitted the full transcript instead of lightweight status");
  check(calls.some((x)=>x[0] === "agent.snapshot"), "terminal status did not fetch the transcript once");
  const secondTurn = root.querySelector("#agent-turn-2");
  check(Boolean(secondTurn), "assistant completion turn missing");
  const secondBody = secondTurn.descendants().find((x)=>x.tagName === "P");
  check(secondBody.textContent.includes("Second line remains copyable."), "assistant response text was not preserved");
  check(secondBody.style.whiteSpace === "pre-wrap", "assistant multiline text is not visibly/copyably preserved");
  check(root.querySelector("#agent-send").disabled === false, "completion did not restore Send");
  check(root.querySelector("#agent-stop").disabled === true, "completion did not disable Stop");

  window.AccessibleChessAgentSurface.apply(
    root,
    {kind:"render",payload:{snapshot:snapshot("completed",[
      {id:"agent-turn-2",role:"assistant",label:"Assistant",text:"Retained answer"}
    ])}},
    invoke,
    (m)=>announcements.push(String(m))
  );
  check(root.querySelector("#agent-turn-1") === null, "expired transcript turn remained in the DOM");
  check(Boolean(root.querySelector("#agent-turn-2")), "retained transcript turn disappeared");

  window.AccessibleChessAgentSurface.render(root, snapshot("running",[
    {id:"agent-turn-1",role:"user",label:"You",text:"Analyze e4"}
  ]), invoke, (m)=>announcements.push(String(m)), "agent-stop", "Action failed");
  root.querySelector("#agent-stop").listeners.click();
  await flush();
  check(calls.some((x)=>x[0] === "agent.cancel"), "Stop did not invoke canonical cancel command");
  check(root.querySelector("#agent-live-status").textContent === "cancelling", "cancel state was not rendered");
  check(!source.includes("innerHTML"), "agent surface must not render model text through innerHTML");
  check(announcements.length === 0, "normal status flow duplicated announcements outside the status region");
  console.log("Agent conversation/NVDA DOM contract PASS");
})().catch((error)=>{ console.error(error); process.exitCode=1; });
