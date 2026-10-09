(function (root) {
  "use strict";

  const ERROR_CODES = new Set([
    "aborted",
    "audio-capture",
    "network",
    "no-speech",
    "not-allowed",
    "service-not-allowed",
  ]);

  function recognitionConstructor(scope) {
    return scope && (scope.SpeechRecognition || scope.webkitSpeechRecognition) || null;
  }

  function voiceCapabilities(scope) {
    return {
      recognition: Boolean(recognitionConstructor(scope)),
      synthesis: Boolean(scope && scope.speechSynthesis && scope.SpeechSynthesisUtterance),
    };
  }

  function boundedRate(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0.5, Math.min(2, number)) : 1;
  }

  class AgentVoiceController {
    constructor(options = {}) {
      this.scope = options.scope || root;
      this.onTranscript = options.onTranscript || function () {};
      this.onState = options.onState || function () {};
      this.language = options.language || function () { return "uk-UA"; };
      this.recognition = null;
      this.listening = false;
      this.speaking = false;
      this.receivedFinal = false;
    }

    capabilities() {
      return voiceCapabilities(this.scope);
    }

    startListening() {
      const Constructor = recognitionConstructor(this.scope);
      if (!Constructor) {
        this.onState({ type: "recognition-unavailable" });
        return false;
      }
      this.stopListening();
      const recognition = new Constructor();
      this.recognition = recognition;
      this.receivedFinal = false;
      recognition.lang = this.language();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      recognition.onstart = () => {
        this.listening = true;
        this.onState({ type: "listening" });
      };
      recognition.onresult = event => {
        let text = "";
        let final = false;
        for (let index = Number(event.resultIndex || 0); index < event.results.length; index += 1) {
          const result = event.results[index];
          const alternative = result && result[0];
          if (alternative && typeof alternative.transcript === "string") text += alternative.transcript;
          final = final || Boolean(result && result.isFinal);
        }
        text = text.trim();
        if (final) this.receivedFinal = true;
        if (text) this.onTranscript({ text, final });
      };
      recognition.onerror = event => {
        const code = ERROR_CODES.has(event && event.error) ? event.error : "recognition-error";
        this.listening = false;
        this.onState({ type: "recognition-error", code });
      };
      recognition.onend = () => {
        if (this.recognition !== recognition) return;
        this.listening = false;
        this.recognition = null;
        this.onState({ type: this.receivedFinal ? "transcript-ready" : "listening-ended" });
      };
      try {
        recognition.start();
        return true;
      } catch (_error) {
        this.recognition = null;
        this.listening = false;
        this.onState({ type: "recognition-error", code: "start-failed" });
        return false;
      }
    }

    stopListening() {
      const recognition = this.recognition;
      this.recognition = null;
      this.listening = false;
      if (recognition) {
        try { recognition.stop(); } catch (_error) {}
        this.onState({ type: "listening-ended" });
      }
      return Boolean(recognition);
    }

    speak(text, rate = 1) {
      const capabilities = this.capabilities();
      const content = String(text || "").trim().slice(0, 12000);
      if (!capabilities.synthesis || !content) {
        this.onState({ type: capabilities.synthesis ? "empty-speech" : "synthesis-unavailable" });
        return false;
      }
      this.cancelSpeech();
      const utterance = new this.scope.SpeechSynthesisUtterance(content);
      utterance.lang = this.language();
      utterance.rate = boundedRate(rate);
      utterance.onstart = () => {
        this.speaking = true;
        this.onState({ type: "speaking" });
      };
      utterance.onend = () => {
        this.speaking = false;
        this.onState({ type: "speech-ended" });
      };
      utterance.onerror = () => {
        this.speaking = false;
        this.onState({ type: "synthesis-error" });
      };
      this.scope.speechSynthesis.speak(utterance);
      return true;
    }

    cancelSpeech() {
      const synthesis = this.scope && this.scope.speechSynthesis;
      if (!synthesis || typeof synthesis.cancel !== "function") return false;
      synthesis.cancel();
      this.speaking = false;
      return true;
    }
  }

  root.AccessibleChessAgentVoice = {
    AgentVoiceController,
    boundedRate,
    voiceCapabilities,
  };
})(typeof window !== "undefined" ? window : globalThis);
