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
  let activeSourceId = "";
  let providerGeneration = 0;
  let openRequestSerial = 0;
  let announcedSourceIdentity = "";
  let youtubeClockTimer = null;
  let synchronizationSequence = 0;

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
    const nextMessage = String(message || "").slice(0, 4096);
    if (sourceStatus.textContent !== nextMessage) sourceStatus.textContent = nextMessage;
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
    if (![null, "youtube", "browser_local", "host"].includes(value.providerKind)) {
      throw new Error("invalid Media workflow provider");
    }
    if (typeof value.sourceTitle !== "string" || value.sourceTitle.length > 4096) {
      throw new Error("invalid Media workflow source title");
    }
    if (value.providerKind === "browser_local") {
      if (typeof value.sourceId !== "string" || !value.sourceId.startsWith("local:sha256:")) {
        throw new Error("invalid local Media source identity");
      }
      if (typeof value.browserSourceUrl !== "string" || !value.browserSourceUrl.startsWith("file:///")) {
        throw new Error("invalid local Media browser source");
      }
    }
    if (!value.player || typeof value.player !== "object" || Array.isArray(value.player)) {
      throw new Error("invalid Media workflow player state");
    }
    return value;
  }

  function destroyProvider() {
    providerGeneration += 1;
    synchronizationSequence += 1;
    if (youtubeClockTimer !== null) {
      global.clearInterval(youtubeClockTimer);
      youtubeClockTimer = null;
    }
    activeSourceId = "";
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
    const generation = providerGeneration;
    const sourceAtInvocation = activeSourceId;
    const invoke = requiredApi("media_workflow_command");
    const position = command && Number.isSafeInteger(command.positionMs)
      ? command.positionMs
      : null;
    return invoke(String(command.action || ""), position).then(function (next) {
      if (generation !== providerGeneration || sourceAtInvocation !== activeSourceId) {
        throw new Error("stale media command response");
      }
      renderEnvelope(next, true);
      return validateEnvelope(next).player;
    });
  }

  function syncYouTubeSnapshot(snapshot, observedGeneration) {
    // The embedded player's callbacks are untrusted timing observations.
    // A callback issued before a different local/YouTube source was opened
    // must never republish a prior source over the new canonical chess state.
    const generation = observedGeneration === undefined
      ? providerGeneration : observedGeneration;
    if (!snapshot || typeof snapshot !== "object" ||
        typeof snapshot.sourceId !== "string" ||
        snapshot.sourceId !== activeSourceId ||
        generation !== providerGeneration) {
      return Promise.resolve(null);
    }
    if (snapshot.providerId === "youtube_iframe_v1" &&
        (snapshot.ok !== true || snapshot.ready !== true)) {
      synchronizationSequence += 1;
      if (snapshot.ok === false) {
        const code = snapshot.errorCode;
        const reason = code === 101 || code === 150
          ? uiText("Автор заборонив вбудовування відео.", "Video embedding is disabled by its owner.")
          : code === 100
            ? uiText("Відео приватне або видалене.", "Video is private or unavailable.")
            : code === 153
              ? uiText("YouTube не отримав HTTP Referer або ідентифікатор клієнта.",
                       "YouTube requires an HTTP Referer or client identity.")
              : uiText("YouTube відхилив відтворення.", "YouTube could not play this source.");
        setStatus(reason, true);
      }
      return Promise.resolve(null);
    }
    if (snapshot.providerId === "youtube_iframe_v1" && snapshot.autoplayBlocked === true) {
      setStatus(uiText(
        "YouTube заблокував автоматичне або програмне відтворення. Натисніть кнопку програвача.",
        "YouTube playback was blocked. Use the player's own Play button."
      ), true);
    }
    if (!Number.isSafeInteger(snapshot.positionMs) || snapshot.positionMs < 0 ||
        (snapshot.durationMs !== null &&
         (!Number.isSafeInteger(snapshot.durationMs) ||
          snapshot.durationMs < snapshot.positionMs))) {
      synchronizationSequence += 1;
      setStatus(uiText("Некоректний час відео.", "Invalid video timing."), true);
      return Promise.resolve(null);
    }
    const synchronize = requiredApi("media_workflow_sync_playback");
    const requestSequence = ++synchronizationSequence;
    return synchronize(
      snapshot.sourceId,
      snapshot.positionMs,
      snapshot.durationMs,
      snapshot.playbackState
    ).then(function (next) {
      if (generation !== providerGeneration ||
          requestSequence !== synchronizationSequence ||
          snapshot.sourceId !== activeSourceId) return null;
      renderEnvelope(next, false);
      return validateEnvelope(next);
    }).catch(function () {
      if (generation !== providerGeneration) return null;
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
    return syncYouTubeSnapshot(snapshot).then(function (qualified) {
      if (qualified === null) throw new Error("stale or unconfirmed media clock");
      return hostCommand(command);
    });
  }

  function localVideoCommand(command) {
    if (!activeAdapter) {
      return Promise.reject(new Error("local video adapter unavailable"));
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
        return Promise.reject(new Error("invalid local seek position"));
      }
      activeAdapter.seek(command.positionMs);
      global.setTimeout(function () {
        try { activeAdapter.refresh(); } catch (_error) {}
      }, 0);
      return Promise.resolve(undefined);
    }
    const snapshot = activeAdapter.snapshot();
    return syncYouTubeSnapshot(snapshot).then(function (qualified) {
      if (qualified === null) throw new Error("stale or unconfirmed media clock");
      return hostCommand(command);
    });
  }

  function renderEnvelope(value, focusAfterRender) {
    const state = validateEnvelope(value);
    const renderer = playerRenderer();
    activeProviderKind = state.providerKind;
    if (state.sourceTitle && announcedSourceIdentity !== state.sourceId) {
      announcedSourceIdentity = state.sourceId;
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
    const runner = state.providerKind === "youtube"
      ? youtubeCommand
      : state.providerKind === "browser_local"
        ? localVideoCommand
        : hostCommand;
    const focused = documentRef.activeElement;
    const preserveFocusId = focused && typeof focused.id === "string" &&
      focused.id && typeof playerHost.contains === "function" &&
      playerHost.contains(focused) ? focused.id : "";
    renderer.render(playerHost, state.player, runner, focusAfterRender === true);
    // Media progress can refresh while a blind user operates the controls.
    // Retain focus on the same semantic button/slider instead of losing it
    // when the accessible player replaces its children.
    if (preserveFocusId && typeof documentRef.getElementById === "function") {
      const nextFocused = documentRef.getElementById(preserveFocusId);
      if (nextFocused && typeof nextFocused.focus === "function") {
        nextFocused.focus();
      }
    }
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
    youtubePromise = youtubePromise.catch(function (error) {
      // Failed network loads must be retryable after reconnection.
      youtubePromise = null;
      throw error;
    });
    return youtubePromise;
  }

  function activateYouTube(envelope, sourceText) {
    const requested = openRequestSerial;
    const expectedGeneration = providerGeneration;
    renderEnvelope(envelope, false);
    setStatus(
      uiText(
        "Підключення до документованого YouTube IFrame Player API.",
        "Connecting to the documented YouTube IFrame Player API."
      ),
      false
    );
    return ensureYouTubeApi().then(function (YT) {
      if (requested !== openRequestSerial || expectedGeneration !== providerGeneration) return false;
      const namespace = global.AccessibleChessYouTubeIframePlayback;
      if (
        !namespace ||
        typeof namespace.YouTubeIframePlaybackAdapter !== "function"
      ) {
        throw new Error("YouTube playback adapter unavailable");
      }
      destroyProvider();
      activeSourceId = envelope.sourceId;
      const generation = providerGeneration;
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
          syncYouTubeSnapshot(snapshot, generation);
        },
      });
      activeProviderKind = "youtube";
      youtubeClockTimer = global.setInterval(function () {
        if (generation !== providerGeneration || !activeAdapter) return;
        try {
          const current = activeAdapter.snapshot();
          if (current.ok === true && current.ready === true) activeAdapter.refresh();
        } catch (_error) {
          // The provider state remains uncertain; no chess clock promotion.
        }
      }, 1000);
      return true;
    }).catch(function () {
      if (requested !== openRequestSerial) return false;
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

  function activateLocalVideo(envelope) {
    renderEnvelope(envelope, false);
    const namespace = global.AccessibleChessLocalVideoPlayback;
    if (!namespace || typeof namespace.BrowserLocalVideoPlaybackAdapter !== "function") {
      setStatus(
        uiText("Локальний відеопрогравач недоступний.", "The local video player is unavailable."),
        true
      );
      return Promise.resolve(false);
    }
    try {
      destroyProvider();
      activeSourceId = envelope.sourceId;
      const generation = providerGeneration;
      const mount = documentRef.createElement("div");
      mount.id = "section47-local-video-player";
      providerHost.appendChild(mount);
      activeAdapter = new namespace.BrowserLocalVideoPlaybackAdapter({
        element: mount,
        sourceUrl: envelope.browserSourceUrl,
        sourceId: envelope.sourceId,
        onSnapshot: function (snapshot) {
          syncYouTubeSnapshot(snapshot, generation);
        },
      });
      activeProviderKind = "browser_local";
      return Promise.resolve(true);
    } catch (_error) {
      setStatus(
        uiText(
          "Не вдалося відкрити локальне відео; шахова позиція не змінена.",
          "The local video could not be opened; the chess position was not changed."
        ),
        true
      );
      return Promise.resolve(false);
    }
  }

  function activateOpened(value, sourceText) {
    const envelope = validateEnvelope(value);
    if (envelope.providerKind === "youtube") {
      return activateYouTube(envelope, sourceText);
    }
    if (envelope.providerKind === "browser_local") {
      return activateLocalVideo(envelope);
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
    const request = ++openRequestSerial;
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
      if (request !== openRequestSerial) return false;
      return activateOpened(value, sourceText);
    }).catch(function () {
      if (request !== openRequestSerial) return false;
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
    const request = ++openRequestSerial;
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
      if (request !== openRequestSerial) return false;
      activeSourceText = "";
      return activateOpened(value, "");
    }).catch(function () {
      if (request !== openRequestSerial) return false;
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
