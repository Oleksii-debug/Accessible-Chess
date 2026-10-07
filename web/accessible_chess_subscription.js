(() => {
"use strict";

const byId = (id) => document.getElementById(id);
const statusNode = byId("status");
const errorNode = byId("error");
const plansNode = byId("plans");
const cadenceNode = byId("cadence");
const navigationLink = byId("navigation-link");
const cancelBox = byId("cancel-confirmation");
let state = {};
let busy = false;

function announce(message) {
  statusNode.textContent = "";
  window.setTimeout(() => { statusNode.textContent = String(message || ""); }, 10);
}

function fail(message) {
  errorNode.textContent = "";
  window.setTimeout(() => { errorNode.textContent = String(message || "Не вдалося виконати дію."); }, 10);
}

async function request(path, options) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    ...options
  });
  const body = await response.json();
  if (!response.ok || !body || body.ok !== true) {
    throw new Error(body && body.error ? body.error : "Не вдалося виконати дію.");
  }
  return body;
}

function selectedPlan() {
  const input = document.querySelector('input[name="plan"]:checked');
  return input ? String(input.value) : "";
}

function currentPlanRecord() {
  const id = selectedPlan();
  const plans = Array.isArray(state.plans) ? state.plans : [];
  return plans.find((item) => item && item.plan_id === id) || null;
}

function renderCadences() {
  cadenceNode.replaceChildren();
  const item = currentPlanRecord();
  const values = item && Array.isArray(item.cadences) ? item.cadences : ["none"];
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = String(value);
    cadenceNode.appendChild(option);
  });
  const requiresBilling = Boolean(item && item.requires_billing);
  byId("checkout").disabled = !requiresBilling;
  const features = item && Array.isArray(item.feature_ids) ? item.feature_ids : [];
  byId("plan-details").textContent = features.length
    ? "Можливості плану: " + features.join(", ")
    : "";
}

function renderPlans() {
  plansNode.replaceChildren();
  const plans = Array.isArray(state.plans) ? state.plans : [];
  plans.forEach((item, index) => {
    if (!item || typeof item.plan_id !== "string") return;
    const line = document.createElement("div");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "plan";
    input.value = item.plan_id;
    input.id = "plan-" + item.plan_id;
    input.checked = item.plan_id === state.current_plan || (!state.current_plan && index === 0);
    input.addEventListener("change", renderCadences);
    const label = document.createElement("label");
    label.htmlFor = input.id;
    label.textContent = String(item.label || item.plan_id);
    line.append(input, label);
    plansNode.appendChild(line);
  });
  renderCadences();
}

function showNavigation(url, label) {
  navigationLink.hidden = true;
  navigationLink.removeAttribute("href");
  if (!url) return;
  navigationLink.href = String(url);
  navigationLink.textContent = String(label || "Продовжити");
  navigationLink.hidden = false;
  navigationLink.focus({preventScroll: true});
}

function render(body) {
  state = body.subscription && typeof body.subscription === "object" ? body.subscription : {};
  byId("account-state").textContent = body.signed_in
    ? "Ви увійшли до облікового запису."
    : "Ви ще не увійшли. Реєстрація доступна нижче.";
  byId("confirmation").textContent = String(
    state.status_message || state.entitlement_state || "Стан підписки ще не отримано."
  );
  const safety = Array.isArray(state.data_safety_features) ? state.data_safety_features : [];
  byId("data-safety").textContent = safety.length ? safety.join(", ") : "";
  byId("manage").disabled = !body.signed_in;
  byId("cancel-start").disabled = !body.signed_in;
  byId("refresh-confirmation").disabled = !body.signed_in;
  renderPlans();
}

async function refresh(focus = false) {
  if (busy) return;
  busy = true;
  try {
    errorNode.textContent = "";
    const body = await request("/v1/subscription/snapshot", {method: "GET"});
    render(body);
    if (focus) byId("main").focus({preventScroll: true});
  } catch (error) {
    fail(error && error.message);
  } finally {
    busy = false;
  }
}

async function action(name, payload = {}) {
  if (busy) return null;
  busy = true;
  try {
    errorNode.textContent = "";
    navigationLink.hidden = true;
    const body = await request("/v1/subscription/command", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action: name, payload})
    });
    const result = body.result && typeof body.result === "object" ? body.result : {};
    announce(String(result.message || "Дію виконано."));
    if (result.navigation_url) {
      showNavigation(result.navigation_url, result.navigation_label);
    }
    return result;
  } catch (error) {
    fail(error && error.message);
    return null;
  } finally {
    busy = false;
  }
}

byId("register").addEventListener("click", async () => {
  await action("register");
});

byId("select-plan").addEventListener("click", async () => {
  const planId = selectedPlan();
  if (!planId) {
    fail("Виберіть план.");
    return;
  }
  const result = await action("select_plan", {plan_id: planId});
  if (result) await refresh(false);
});

byId("checkout").addEventListener("click", async () => {
  const planId = selectedPlan();
  const cadence = String(cadenceNode.value || "");
  if (!planId || !cadence || cadence === "none") {
    fail("Виберіть платний план і період оплати.");
    return;
  }
  await action("begin_checkout", {plan_id: planId, cadence});
});

byId("refresh-confirmation").addEventListener("click", async () => {
  const result = await action("refresh_confirmation");
  if (result) await refresh(false);
});

byId("manage").addEventListener("click", async () => {
  await action("open_manage");
});

byId("cancel-start").addEventListener("click", () => {
  cancelBox.hidden = false;
  byId("cancel-confirm").focus({preventScroll: true});
});

byId("cancel-back").addEventListener("click", () => {
  cancelBox.hidden = true;
  byId("cancel-start").focus({preventScroll: true});
});

byId("cancel-confirm").addEventListener("click", async () => {
  const result = await action("cancel");
  cancelBox.hidden = true;
  if (result) await refresh(false);
});

refresh(true);
})();
