(function (global) {
  "use strict";

  if (global.__accessibleChessLocalProfileInstalled) return;
  global.__accessibleChessLocalProfileInstalled = true;

  const documentRef = global.document;
  const live = documentRef && documentRef.getElementById("live");
  const nav = documentRef && documentRef.getElementById("v2-navigation");
  if (!documentRef || !live || !nav) return;

  const MAX_DISPLAY_NAME = 80;
  const MAX_ANNOUNCEMENT = 1200;
  let profileState = null;
  let mutationPending = false;
  let returnFocusId = "";
  let featureAvailable = false;

  function api() {
    return global.pywebview && global.pywebview.api;
  }

  function language() {
    return documentRef.documentElement.lang === "en" ? "en" : "uk";
  }

  function uiText(uk, en) {
    return language() === "en" ? en : uk;
  }

  function plainObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function boundedText(value, limit, allowBlank) {
    if (typeof value !== "string" || value.length > limit || /[\u0000-\u001f\u007f]/.test(value)) {
      return null;
    }
    if (!allowBlank && !value.trim()) return null;
    return value;
  }

  function announcementFrom(result) {
    if (!plainObject(result) || result.announcement === undefined) return "";
    return boundedText(result.announcement, MAX_ANNOUNCEMENT, true);
  }

  function parseProfileState(result) {
    if (!plainObject(result) || typeof result.ok !== "boolean") return null;
    if (Object.prototype.hasOwnProperty.call(result, "profile_id") ||
        Object.prototype.hasOwnProperty.call(result, "profileId")) return null;

    const announcement = announcementFrom(result);
    if (announcement === null) return null;
    const stateChanged = result.stateChanged === undefined
      ? false
      : result.stateChanged;
    if (typeof stateChanged !== "boolean") return null;

    if (result.exists === undefined) {
      if (result.ok || stateChanged) return null;
      return { ok: false, stateChanged: false, announcement, hasState: false };
    }
    if (typeof result.exists !== "boolean") return null;

    if (!result.exists) {
      const displayName = result.displayName === undefined ? "" : result.displayName;
      const generatedAlias = result.generatedAlias === undefined ? false : result.generatedAlias;
      const recoveryRequired = result.recoveryRequired === undefined ? false : result.recoveryRequired;
      if (boundedText(displayName, MAX_DISPLAY_NAME, true) === null || displayName !== "" ||
          generatedAlias !== false || recoveryRequired !== false) return null;
      return {
        ok: result.ok,
        exists: false,
        displayName: "",
        generatedAlias: false,
        recoveryRequired: false,
        stateChanged,
        announcement,
        hasState: true
      };
    }

    const fullStatePresent = result.displayName !== undefined &&
      result.generatedAlias !== undefined && result.recoveryRequired !== undefined;
    if (!fullStatePresent) {
      if (result.ok || stateChanged) return null;
      return { ok: false, stateChanged: false, announcement, hasState: false };
    }
    const displayName = boundedText(result.displayName, MAX_DISPLAY_NAME, false);
    if (displayName === null || typeof result.generatedAlias !== "boolean" ||
        typeof result.recoveryRequired !== "boolean") return null;
    if (result.revision !== undefined &&
        (!Number.isSafeInteger(result.revision) || result.revision < 1)) return null;
    return {
      ok: result.ok,
      exists: true,
      displayName,
      generatedAlias: result.generatedAlias,
      recoveryRequired: result.recoveryRequired,
      revision: result.revision,
      stateChanged,
      announcement,
      hasState: true
    };
  }

  function announce(message) {
    const text = boundedText(message, MAX_ANNOUNCEMENT, false);
    if (text === null) return;
    live.textContent = "";
    global.setTimeout(function () { live.textContent = text; }, 20);
  }

  function focusById(id) {
    if (typeof id !== "string" || !/^[A-Za-z0-9_-]{1,160}$/.test(id)) return false;
    const target = documentRef.getElementById(id);
    if (!target || typeof target.focus !== "function" || target.hidden) return false;
    target.focus({ preventScroll: true });
    return documentRef.activeElement === target;
  }

  const profileButton = documentRef.createElement("button");
  profileButton.type = "button";
  profileButton.id = "v2-profile-button";
  profileButton.disabled = true;
  nav.appendChild(profileButton);

  const dialog = documentRef.createElement("dialog");
  dialog.id = "v2-profile-dialog";
  const heading = documentRef.createElement("h2");
  heading.id = "v2-profile-heading";
  dialog.setAttribute("aria-labelledby", heading.id);
  const description = documentRef.createElement("p");
  description.id = "v2-profile-description";
  const status = documentRef.createElement("p");
  status.id = "v2-profile-status";
  status.className = "block";
  status.setAttribute("aria-live", "off");
  const label = documentRef.createElement("label");
  const nameInput = documentRef.createElement("input");
  nameInput.type = "text";
  nameInput.id = "v2-profile-name";
  nameInput.maxLength = MAX_DISPLAY_NAME;
  nameInput.autocomplete = "off";
  nameInput.spellcheck = false;
  nameInput.setAttribute("aria-describedby", "v2-profile-description v2-profile-status");
  label.htmlFor = nameInput.id;
  const actions = documentRef.createElement("div");
  actions.className = "row";
  const saveButton = documentRef.createElement("button");
  saveButton.type = "button";
  saveButton.id = "v2-profile-save";
  const skipButton = documentRef.createElement("button");
  skipButton.type = "button";
  skipButton.id = "v2-profile-skip";
  const repairButton = documentRef.createElement("button");
  repairButton.type = "button";
  repairButton.id = "v2-profile-repair";
  repairButton.setAttribute("aria-describedby", status.id);
  const closeButton = documentRef.createElement("button");
  closeButton.type = "button";
  closeButton.id = "v2-profile-close";
  actions.append(saveButton, skipButton, repairButton, closeButton);
  dialog.append(
    heading,
    description,
    status,
    label,
    documentRef.createElement("br"),
    nameInput,
    actions
  );
  documentRef.body.appendChild(dialog);

  function render(preserveDraft) {
    heading.textContent = uiText("Локальний профіль", "Local profile");
    description.textContent = uiText(
      "Вкажіть ім’я, яке буде показано в Accessible Chess. Можна пропустити: тоді програма створить випадковий локальний псевдонім. Ім’я можна змінити пізніше.",
      "Choose the name shown in Accessible Chess. You may skip this step; the app will create a random local alias. You can rename it later."
    );
    label.textContent = uiText("Ім’я профілю", "Profile name");
    const exists = !!(profileState && profileState.exists);
    const recoveryRequired = exists && profileState.recoveryRequired === true;
    const displayName = exists ? profileState.displayName : "";
    profileButton.textContent = exists
      ? uiText("Профіль: ", "Profile: ") + displayName
      : uiText("Налаштувати профіль", "Set up profile");
    saveButton.textContent = exists
      ? uiText("Змінити ім’я", "Rename")
      : uiText("Зберегти ім’я", "Save name");
    skipButton.textContent = uiText(
      "Пропустити й створити псевдонім",
      "Skip and create an alias"
    );
    repairButton.textContent = uiText(
      "Перевірити або відновити профіль",
      "Check or recover profile"
    );
    closeButton.textContent = uiText("Закрити", "Close");
    if (!preserveDraft) nameInput.value = displayName;
    skipButton.hidden = exists;
    repairButton.hidden = !recoveryRequired;
    closeButton.hidden = !exists;
    dialog.setAttribute("aria-busy", mutationPending ? "true" : "false");
    saveButton.disabled = mutationPending || recoveryRequired || !featureAvailable;
    skipButton.disabled = mutationPending || !featureAvailable;
    repairButton.disabled = mutationPending || !featureAvailable;
    closeButton.disabled = mutationPending;
    nameInput.disabled = mutationPending || recoveryRequired || !featureAvailable;
    profileButton.disabled = !featureAvailable;
    status.textContent = exists
      ? (recoveryRequired
        ? uiText(
          "Профіль відкрито з резервної копії. Виберіть відновлення перед перейменуванням.",
          "The profile was opened from its recovery copy. Recover it before renaming."
        )
        : profileState.generatedAlias
          ? uiText(
            "Використовується випадковий локальний псевдонім.",
            "A random local alias is in use."
          )
          : uiText("Профіль збережено локально.", "The profile is stored locally."))
      : uiText("Профіль ще не створено.", "No profile has been created yet.");
  }

  function focusPrimary() {
    if (profileState && profileState.recoveryRequired === true &&
        !repairButton.hidden && !repairButton.disabled) {
      repairButton.focus({ preventScroll: true });
      return;
    }
    if (!nameInput.disabled) {
      nameInput.focus({ preventScroll: true });
      if (typeof nameInput.select === "function") nameInput.select();
      return;
    }
    if (!closeButton.hidden && !closeButton.disabled) closeButton.focus({ preventScroll: true });
  }

  function showDialog() {
    if (!dialog.open) {
      const active = documentRef.activeElement;
      returnFocusId = active && typeof active.id === "string" ? active.id : "";
      dialog.showModal();
    }
    global.setTimeout(focusPrimary, 0);
  }

  function featureUnavailable() {
    featureAvailable = false;
    profileButton.disabled = true;
    const message = uiText(
      "Локальний профіль недоступний. Наявні дані профілю не змінено.",
      "Local profile is unavailable. Existing profile data was not changed."
    );
    status.textContent = message;
    if (dialog.open) dialog.close();
    announce(message);
    return false;
  }

  function beginMutation() {
    if (mutationPending || !featureAvailable) return false;
    mutationPending = true;
    render(true);
    return true;
  }

  function endMutation() {
    mutationPending = false;
    render(true);
  }

  function applyResult(raw, closeOnSuccess) {
    const parsed = parseProfileState(raw);
    if (!parsed) return featureUnavailable();
    if (parsed.hasState && (parsed.ok || parsed.stateChanged)) profileState = parsed;
    if (parsed.hasState) render(true);
    if (parsed.announcement) announce(parsed.announcement);
    if (!parsed.ok) return false;
    if (closeOnSuccess && parsed.hasState && parsed.recoveryRequired !== true && dialog.open) {
      dialog.close();
    }
    return true;
  }

  function invoke(method, args) {
    const bridge = api();
    if (!bridge || typeof bridge[method] !== "function") {
      return Promise.reject(new Error("profile bridge unavailable"));
    }
    let result;
    try {
      result = bridge[method].apply(bridge, args || []);
    } catch (error) {
      return Promise.reject(error);
    }
    return Promise.resolve(result);
  }

  function loadProfile(openIfMissing) {
    return invoke("profile_snapshot", []).then(function (raw) {
      const parsed = parseProfileState(raw);
      if (!parsed || !parsed.ok || !parsed.hasState) return featureUnavailable();
      featureAvailable = true;
      profileState = parsed;
      render(false);
      if (openIfMissing && (!parsed.exists || parsed.recoveryRequired)) showDialog();
      return true;
    }, featureUnavailable);
  }

  profileButton.addEventListener("click", function () {
    loadProfile(false).then(function (ok) { if (ok) showDialog(); });
  });

  dialog.addEventListener("cancel", function (event) {
    if (mutationPending || !profileState || !profileState.exists) event.preventDefault();
  });

  dialog.addEventListener("close", function () {
    const target = returnFocusId;
    returnFocusId = "";
    if (target && focusById(target)) return;
    if (!profileButton.disabled) profileButton.focus({ preventScroll: true });
  });

  function saveName() {
    if (profileState && profileState.recoveryRequired) {
      announce(uiText(
        "Відновіть локальний профіль перед зміною імені.",
        "Recover the local profile before renaming it."
      ));
      if (!repairButton.disabled) repairButton.focus({ preventScroll: true });
      return;
    }
    const rename = !!(profileState && profileState.exists);
    const method = rename ? "profile_rename" : "profile_create";
    const args = rename ? [nameInput.value] : [nameInput.value, false];
    if (!beginMutation()) return;
    invoke(method, args).then(function (raw) {
      const ok = applyResult(raw, true);
      endMutation();
      if (!ok || dialog.open) focusPrimary();
    }, function () {
      endMutation();
      announce(uiText("Не вдалося оновити профіль.", "Could not update the profile."));
      focusPrimary();
    });
  }

  saveButton.addEventListener("click", saveName);
  nameInput.addEventListener("keydown", function (event) {
    const resolve = global.accessibleChessKeymapAction;
    let actionId = "";
    let resolverReady = false;
    if (typeof resolve === "function") {
      const resolved = resolve(event, "profile_dialog");
      if (resolved !== null && resolved !== undefined) {
        resolverReady = true;
        actionId = typeof resolved === "string" ? resolved : "";
      }
    }
    if (
      !resolverReady &&
      !event.altKey && !event.ctrlKey && !event.shiftKey && !event.metaKey &&
      event.key === "Enter"
    ) {
      actionId = "profile.save_name";
    }
    if (actionId !== "profile.save_name") return;
    event.preventDefault();
    if (typeof event.stopPropagation === "function") event.stopPropagation();
    saveName();
  });

  skipButton.addEventListener("click", function () {
    if (!beginMutation()) return;
    invoke("profile_create", ["", true]).then(function (raw) {
      const ok = applyResult(raw, true);
      endMutation();
      if (!ok || dialog.open) focusPrimary();
    }, function () {
      endMutation();
      announce(uiText("Не вдалося створити псевдонім.", "Could not create an alias."));
      focusPrimary();
    });
  });

  repairButton.addEventListener("click", function () {
    if (!beginMutation()) return;
    invoke("profile_repair", []).then(function (raw) {
      const ok = applyResult(raw, false);
      endMutation();
      if (ok) nameInput.value = profileState ? profileState.displayName : "";
      focusPrimary();
    }, function () {
      endMutation();
      announce(uiText("Не вдалося відновити профіль.", "Could not recover the profile."));
      focusPrimary();
    });
  });

  closeButton.addEventListener("click", function () {
    if (profileState && profileState.exists && !mutationPending) dialog.close();
  });

  if (typeof global.MutationObserver === "function") {
    const observer = new global.MutationObserver(function () { render(true); });
    observer.observe(documentRef.documentElement, { attributes: true, attributeFilter: ["lang"] });
  }

  render(false);
  loadProfile(true);
})(window);
