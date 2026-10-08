(function (global) {
  "use strict";
  if (global.__accessibleChessSection20MediaWorkflowInstalled) return;
  global.__accessibleChessSection20MediaWorkflowInstalled = true;

  const documentRef = global.document;
  const workspace = documentRef.getElementById("v2-workspace");
  const originalMain = documentRef.getElementById("main-content");
  const parent = workspace && workspace.parentNode
    ? workspace.parentNode
    : originalMain && originalMain.parentNode
      ? originalMain.parentNode
      : null;
  if (!parent) return;

  let activeAdapter = null;
  let activeProviderKind = null;
  let activeSourceText = "";
  let youtubePromise = null;

  function language() {
    return documentRef.documentElement && documentRef.documentElement.lang === "en"
      ? "en"
      : "uk";
  }

  function uiText(uk, en) {
    return language() === "en" ? en : uk;
  }

  function api() {
    return global.pywebview && global.pywebview.api;
  }

  function requiredApi(name) {
    const bridge = api();
    if (!bridge || typeof bridge[name] !== "function") {
      throw new Error("Media workflow bridge unavailable");
    }
    return bridge[name].bind(bridge);
  }

  const region = documentRef.createElement("section");
  region.id = "section20-media-workflow";
  region.setAttribute("aria-labelledby", "section20-media-heading");

  const heading = documentRef.createElement("h2");
  heading.id = "section20-media-heading";
  heading.textContent = "Media";
  region.appendChild(heading);

  const sourceLabel = documentRef.createElement("label");
  sourceLabel.id = "section20-media-source-label";
  sourceLabel.setAttribute("for", "section20-media-source");
  region.appendChild(sourceLabel);

  const sourceInput = documentRef.createElement("input");
  sourceInput.id = "section20-media-source";
  sourceInput.setAttribute("type", "text");
  sourceInput.setAttribute("autocomplete", "off");
  sourceInput.setAttribute("spellcheck", "false");
  sourceInput.setAttribute("aria-describedby", "section20-media-open-status");
  region.appendChild(sourceInput);

  const pastedOpen = documentRef.createElement("button");
  pastedOpen.id = "section20-media-open-pasted";
  pastedOpen.setAttribute("type", "button");
  region.appendChild(pastedOpen);

  const localOpen = documentRef.createElement("button");
  localOpen.id = "section20-media-open-local";
  localOpen.setAttribute("type", "button");
  region.appendChild(localOpen);

  const sourceStatus = documentRef.createElement("p");
  sourceStatus.id = "section20-media-open-status";
  sourceStatus.setAttribute("role", "status");
  sourceStatus.setAttribute("aria-live", "polite");
  sourceStatus.setAttribute("aria-atomic", "true");
  sourceStatus.setAttribute("tabindex", "-1");
  region.appendChild(sourceStatus);

  const providerHost = documentRef.createElement("div");
  providerHost.id = "section20-media-provider";
  region.appendChild(providerHost);

  const playerHost = documentRef.createElement("div");
  playerHost.id = "section20-media-player";
  region.appendChild(playerHost);

  if (originalMain && originalMain.parentNode === parent) {
    parent.insertBefore(region, originalMain);
  } else {
    parent.appendChild(region);
  }

  function localizeControls() {
    sourceLabel.textContent = uiText(
      "Посилання або ідентифікатор медіа",
      "Media URL or identifier"
    );
    sourceInput.setAttribute(
      "placeholder",
      uiText("Вставте підтримуване медіа", "Paste supported media")
    );
    pastedOpen.textContent = uiText("Відкрити вставлене медіа", "Open pasted media");
    localOpen.textContent = uiText("Відкрити локальне медіа", "Open local media");
    region.setAttribute(
      "aria-label",
      uiText("Повний workflow медіа", "Complete Media workflow")
    );
  }

  function setStatus(message, urgent) {
    sourceStatus.setAttribute("aria-live", urgent ? "assertive" : "polite");
    sourceStatus.textContent = String(message || "").slice(0, 4096);
  }

  function playerRenderer() {
    const value = global.AccessibleChessRecordedMediaPlayer;
    return value && typeof value.render === "function" ? value : null;
  }

  function validateEnvelope(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("invalid Media workflow state");
    }
    if (typeof value.ok !== "boolean") throw new Error("invalid Media workflow ok flag");
    if (![null, "youtube", "host"].includes(value.providerKind)) {
      throw new Error("invalid Media workflow provider");
    }
    if (typeof value.sourceTitle !== "string" || value.sourceTitle.length > 4096) {
      throw new Error("invalid Media workflow source title");
    }
    if (!value.player || typeof value.player !== "object" || Array.isArray(value.player)) {
      throw new Error("invalid Media workflow player state");
    }
    return value;
  }

  function destroyProvider() {
    if (activeAdapter && typeof activeAdapter.destroy === "function") {
      try {
        activeAdapter.destroy();
      } catch (_error) {
        // Provider cleanup must not replace the next source-open transaction.
      }
    }
    activeAdapter = null;
    activeProviderKind = null;
    providerHost.replaceChildren();
  }

  function hostCommand(command) {
    const invoke = requiredApi("media_workflow_command");
    const position = command && Number.isSafeInteger(command.positionMs)
      ? command.positionMs
      : null;
    return invoke(String(command.action || ""), position).then(function (next) {
      renderEnvelope(next, true);
      return validateEnvelope(next).player;
    });
  }

  function syncYouTubeSnapshot(snapshot) {
    const synchronize = requiredApi("media_workflow_sync_playback");
    return synchronize(
      snapshot.sourceId,
      snapshot.positionMs,
      snapshot.durationMs,
      snapshot.playbackState
    ).then(function (next) {
      renderEnvelope(next, false);
      return validateEnvelope(next);
    }).catch(function () {
      setStatus(
        uiText(
          "Не вдалося безпечно синхронізувати час медіа з шаховою позицією.",
          "The media clock could not be synchronized safely with the chess position."
        ),
        true
      );
      return null;
    });
  }

  function youtubeCommand(command) {
    if (!activeAdapter) {
      return Promise.reject(new Error("YouTube adapter unavailable"));
    }
    const action = String(command.action || "");
    if (action === "play") {
      activeAdapter.play();
      return Promise.resolve(undefined);
    }
    if (action === "pause") {
      activeAdapter.pause();
      return Promise.resolve(undefined);
    }
    if (action === "seek") {
      if (!Number.isSafeInteger(command.positionMs) || command.positionMs < 0) {
        return Promise.reject(new Error("invalid seek position"));
      }
      activeAdapter.seek(command.positionMs);
      global.setTimeout(function () {
        try {
          activeAdapter.refresh();
        } catch (_error) {
          setStatus(
            uiText(
              "Не вдалося оновити стан після перемотування.",
              "The player state could not be refreshed after seeking."
            ),
            true
          );
        }
      }, 0);
      return Promise.resolve(undefined);
    }

    const snapshot = activeAdapter.snapshot();
    return syncYouTubeSnapshot(snapshot).then(function () {
      return hostCommand(command);
    });
  }

  function renderEnvelope(value, focusAfterRender) {
    const state = validateEnvelope(value);
    const renderer = playerRenderer();
    activeProviderKind = state.providerKind;
    if (state.sourceTitle) {
      setStatus(
        uiText(
          "Відкрито медіа: " + state.sourceTitle,
          "Opened media: " + state.sourceTitle
        ),
        false
      );
    }
    if (!renderer) {
      setStatus(
        uiText(
          "Доступний програвач медіа не завантажено.",
          "The accessible Media player is not loaded."
        ),
        true
      );
      return false;
    }
    const runner = state.providerKind === "youtube" ? youtubeCommand : hostCommand;
    renderer.render(playerHost, state.player, runner, focusAfterRender === true);
    return true;
  }

  function ensureYouTubeApi() {
    if (
      global.YT &&
      typeof global.YT === "object" &&
      typeof global.YT.Player === "function"
    ) {
      return Promise.resolve(global.YT);
    }
    if (youtubePromise) return youtubePromise;

    youtubePromise = new Promise(function (resolve, reject) {
      const previousReady = global.onYouTubeIframeAPIReady;
      let settled = false;
      global.onYouTubeIframeAPIReady = function () {
        if (typeof previousReady === "function") {
          try {
            previousReady();
          } catch (_error) {
            // Another consumer must not suppress this workflow's ready signal.
          }
        }
        if (
          !global.YT ||
          typeof global.YT !== "object" ||
          typeof global.YT.Player !== "function"
        ) {
          if (!settled) {
            settled = true;
            reject(new Error("YouTube IFrame API did not expose YT.Player"));
          }
          return;
        }
        if (!settled) {
          settled = true;
          resolve(global.YT);
        }
      };

      const script = documentRef.createElement("script");
      script.id = "section20-youtube-iframe-api";
      script.setAttribute("src", "https://www.youtube.com/iframe_api");
      script.setAttribute("async", "");
      script.addEventListener("error", function () {
        if (!settled) {
          settled = true;
          reject(new Error("YouTube IFrame API failed to load"));
        }
      });
      (documentRef.head || documentRef.documentElement).appendChild(script);
    });
    return youtubePromise;
  }

  function activateYouTube(envelope, sourceText) {
    renderEnvelope(envelope, false);
    setStatus(
      uiText(
        "Підключення до документованого YouTube IFrame Player API.",
        "Connecting to the documented YouTube IFrame Player API."
      ),
      false
    );
    return ensureYouTubeApi().then(function (YT) {
      const namespace = global.AccessibleChessYouTubeIframePlayback;
      if (
        !namespace ||
        typeof namespace.YouTubeIframePlaybackAdapter !== "function"
      ) {
        throw new Error("YouTube playback adapter unavailable");
      }
      destroyProvider();
      const mount = documentRef.createElement("div");
      mount.id = "section20-youtube-player";
      providerHost.appendChild(mount);
      const origin = global.location && typeof global.location.origin === "string"
        ? global.location.origin
        : "";
      activeAdapter = new namespace.YouTubeIframePlaybackAdapter({
        YT: YT,
        element: mount,
        source: sourceText,
        origin: origin,
        onSnapshot: function (snapshot) {
          syncYouTubeSnapshot(snapshot);
        },
      });
      activeProviderKind = "youtube";
      return true;
    }).catch(function () {
      setStatus(
        uiText(
          "YouTube IFrame Player недоступний. Джерело не запущено; шахова позиція не змінена.",
          "YouTube IFrame Player is unavailable. The source was not started and the chess position was not changed."
        ),
        true
      );
      return false;
    });
  }

  function activateOpened(value, sourceText) {
    const envelope = validateEnvelope(value);
    if (envelope.providerKind === "youtube") {
      return activateYouTube(envelope, sourceText);
    }
    destroyProvider();
    renderEnvelope(envelope, false);
    return Promise.resolve(envelope.ok);
  }

  function openPasted() {
    const sourceText = String(sourceInput.value || "").trim();
    if (!sourceText) {
      setStatus(
        uiText("Вставте джерело медіа.", "Paste a media source first."),
        true
      );
      sourceInput.focus();
      return Promise.resolve(false);
    }
    pastedOpen.disabled = true;
    activeSourceText = sourceText;
    let invoke;
    try {
      invoke = requiredApi("media_workflow_open_pasted");
    } catch (_error) {
      pastedOpen.disabled = false;
      setStatus(
        uiText("Media workflow недоступний.", "Media workflow is unavailable."),
        true
      );
      return Promise.resolve(false);
    }
    return invoke(sourceText).then(function (value) {
      return activateOpened(value, sourceText);
    }).catch(function () {
      setStatus(
        uiText(
          "Не вдалося відкрити вставлене медіа.",
          "The pasted media source could not be opened."
        ),
        true
      );
      return false;
    }).finally(function () {
      pastedOpen.disabled = false;
    });
  }

  function openLocal() {
    localOpen.disabled = true;
    let invoke;
    try {
      invoke = requiredApi("media_workflow_open_local");
    } catch (_error) {
      localOpen.disabled = false;
      setStatus(
        uiText("Media workflow недоступний.", "Media workflow is unavailable."),
        true
      );
      return Promise.resolve(false);
    }
    return invoke().then(function (value) {
      activeSourceText = "";
      return activateOpened(value, "");
    }).catch(function () {
      setStatus(
        uiText(
          "Не вдалося відкрити локальне медіа.",
          "The local media source could not be opened."
        ),
        true
      );
      return false;
    }).finally(function () {
      localOpen.disabled = false;
    });
  }

  pastedOpen.addEventListener("click", function () {
    openPasted();
  });
  localOpen.addEventListener("click", function () {
    openLocal();
  });
  sourceInput.addEventListener("keydown", function (event) {
    if (event && event.key === "Enter" && !pastedOpen.disabled) {
      event.preventDefault();
      openPasted();
    }
  });

  localizeControls();
  setStatus(
    uiText(
      "Відкрийте локальне медіа або вставте підтримуване посилання.",
      "Open local media or paste a supported media link."
    ),
    false
  );

  global.AccessibleChessSection20MediaWorkflow = Object.freeze({
    openPasted: openPasted,
    openLocal: openLocal,
    refreshLanguage: localizeControls,
    destroyProvider: destroyProvider,
    currentProviderKind: function () { return activeProviderKind; },
    currentSourceText: function () { return activeSourceText; },
  });
})(window);
