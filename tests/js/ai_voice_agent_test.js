const fs = require('fs');
const vm = require('vm');

let recognitionInstance = null;
class FakeRecognition {
  constructor() { recognitionInstance = this; }
  start() { this.onstart(); }
  stop() { this.stopped = true; }
}

class FakeUtterance {
  constructor(text) { this.text = text; }
}

const spoken = [];
const scope = {
  SpeechRecognition: FakeRecognition,
  SpeechSynthesisUtterance: FakeUtterance,
  speechSynthesis: {
    cancelCalls: 0,
    cancel() { this.cancelCalls += 1; },
    speak(utterance) { spoken.push(utterance); },
  },
};

global.window = global;
vm.runInThisContext(fs.readFileSync('web/ai_voice.js', 'utf8'));
const Voice = global.AccessibleChessAgentVoice;
if (!Voice) throw new Error('voice module was not exported');
if (!Voice.voiceCapabilities(scope).recognition || !Voice.voiceCapabilities(scope).synthesis) throw new Error('capability detection failed');
if (Voice.boundedRate(9) !== 2 || Voice.boundedRate(0.1) !== 0.5 || Voice.boundedRate('bad') !== 1) throw new Error('speech rate is not bounded');

const events = [];
const transcripts = [];
const controller = new Voice.AgentVoiceController({
  scope,
  language: () => 'uk-UA',
  onState: event => events.push(event),
  onTranscript: event => transcripts.push(event),
});

if (!controller.startListening()) throw new Error('recognition did not start');
if (!controller.listening || recognitionInstance.lang !== 'uk-UA' || !recognitionInstance.interimResults || recognitionInstance.continuous) throw new Error('recognition configuration failed');
recognitionInstance.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: 'поясни позицію' }], { isFinal: true })] });
if (transcripts.length !== 1 || transcripts[0].text !== 'поясни позицію' || !transcripts[0].final) throw new Error('final transcript was not delivered');
recognitionInstance.onend();
if (controller.listening || events[events.length - 1].type !== 'transcript-ready') throw new Error('final transcript state was overwritten');

if (!controller.startListening()) throw new Error('second recognition did not start');
if (!controller.stopListening() || !recognitionInstance.stopped || events[events.length - 1].type !== 'listening-ended') throw new Error('recognition did not stop');

if (!controller.speak('Відповідь агента', 1.25)) throw new Error('speech did not start');
if (spoken.length !== 1 || spoken[0].text !== 'Відповідь агента' || spoken[0].lang !== 'uk-UA' || spoken[0].rate !== 1.25) throw new Error('utterance configuration failed');
spoken[0].onstart();
if (!controller.speaking) throw new Error('speaking state was not set');
spoken[0].onend();
if (controller.speaking) throw new Error('speaking state was not cleared');

const unavailableEvents = [];
const unavailable = new Voice.AgentVoiceController({ scope: {}, onState: event => unavailableEvents.push(event) });
if (unavailable.startListening() || unavailable.speak('x')) throw new Error('unsupported voice capability must fail closed');
if (unavailableEvents.map(event => event.type).join(',') !== 'recognition-unavailable,synthesis-unavailable') throw new Error('unsupported capability status was not reported');

console.log('ai voice agent executable ok');
