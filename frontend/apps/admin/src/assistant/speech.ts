// The voice of the "Assistant IA" screen (D-314): dictation and reading aloud with what the browser offers.
// Chrome and Edge understand Tunisian ("ar-TN"); only Edge has Tunisian voices of its own, so the server reads the
// answers when it has a voice (see `server_voice`).

/** The languages a question can be dictated in. */
export const DICTATION_LANGUAGES = ["ar-TN", "fr-FR"] as const;
export type DictationLanguage = (typeof DICTATION_LANGUAGES)[number];

const ARABIC_LETTERS = /[؀-ۿ]/;
/** A question whose answer has not come after this long is no longer waited for. */
export const ANSWER_WAIT_MS = 5 * 60_000;

export function isArabic(text: string): boolean {
  return ARABIC_LETTERS.test(text);
}

interface SpokenMessage {
  direction: string;
  created_at: string;
}

/** Whether the conversation ends with a question still waiting for its answer. */
export function isWaiting(messages: readonly SpokenMessage[], now: number = Date.now()): boolean {
  const last = messages.at(-1);
  return last !== undefined && last.direction === "in" && now - new Date(last.created_at).getTime() < ANSWER_WAIT_MS;
}

interface VoiceLike {
  lang: string;
  name: string;
  localService?: boolean;
}

/**
 * The browser voice that reads `text` best: a Tunisian voice, then any Arabic one, for Arabic letters; a French
 * voice otherwise. A "Natural" (online) voice is preferred to a robotic one. Undefined when the browser has none.
 */
export function pickVoice<V extends VoiceLike>(voices: readonly V[], text: string): V | undefined {
  const wanted = isArabic(text) ? ["ar-tn", "ar"] : ["fr-fr", "fr"];
  for (const prefix of wanted) {
    const matching = voices.filter((voice) => voice.lang.toLowerCase().replace("_", "-").startsWith(prefix));
    if (matching.length > 0) return matching.find((voice) => /natural|online/i.test(voice.name)) ?? matching[0];
  }
  return undefined;
}

// ---- Dictation (Web Speech API; not in TypeScript's DOM types) ----

interface RecognitionAlternative {
  transcript: string;
}
interface RecognitionResult {
  isFinal: boolean;
  0: RecognitionAlternative;
}
interface RecognitionEvent {
  results: ArrayLike<RecognitionResult>;
}
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionConstructor = new () => Recognition;

function recognitionConstructor(): RecognitionConstructor | undefined {
  const scope = window as unknown as {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition;
}

export function canDictate(): boolean {
  return typeof window !== "undefined" && recognitionConstructor() !== undefined;
}

export type DictationFailure = "denied" | "silent" | "failed";

export interface Dictation {
  /** Stop listening and keep what was heard. */
  stop(): void;
  /** Stop listening and drop what was heard. */
  cancel(): void;
}

/**
 * Listen to one sentence. `onHeard` gets the words as they come; `onDone` the whole sentence when the person stops
 * talking (or `stop()` is called), empty when nothing was heard.
 */
export function dictate(options: {
  language: DictationLanguage;
  onHeard: (text: string) => void;
  onDone: (text: string) => void;
  onFailure: (failure: DictationFailure) => void;
}): Dictation | undefined {
  const Constructor = recognitionConstructor();
  if (Constructor === undefined) return undefined;
  const recognition = new Constructor();
  let heard = "";
  let cancelled = false;
  let failed = false;
  recognition.lang = options.language;
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onresult = (event) => {
    heard = Array.from(event.results, (result) => result[0].transcript)
      .join(" ")
      .trim();
    options.onHeard(heard);
  };
  recognition.onerror = (event) => {
    if (event.error === "aborted") return;
    failed = true;
    if (event.error === "not-allowed" || event.error === "service-not-allowed") options.onFailure("denied");
    else if (event.error === "no-speech") options.onFailure("silent");
    else options.onFailure("failed");
  };
  recognition.onend = () => {
    if (!cancelled && !failed) options.onDone(heard);
  };
  try {
    recognition.start();
  } catch {
    options.onFailure("failed");
    return undefined;
  }
  return {
    stop: () => recognition.stop(),
    cancel: () => {
      cancelled = true;
      recognition.abort();
    },
  };
}

// ---- Reading aloud ----

export interface Playback {
  stop(): void;
}

function browserVoices(): Promise<SpeechSynthesisVoice[]> {
  const synthesis = window.speechSynthesis;
  const ready = synthesis.getVoices();
  if (ready.length > 0) return Promise.resolve(ready);
  // Chrome loads its voices after the first call.
  return new Promise((resolve) => {
    const done = () => resolve(synthesis.getVoices());
    synthesis.addEventListener("voiceschanged", done, { once: true });
    window.setTimeout(done, 1500);
  });
}

/** What a voice should not read out: the emphasis marks and bullets of a written answer. */
export function spokenText(text: string): string {
  return text.replace(/[*_`#]+|^\s*[-•]\s+/gm, "").trim();
}

/** Read `text` with the browser's own voice. Resolves to undefined when it has no voice for this language. */
export async function speakWithBrowser(text: string, onEnd: () => void): Promise<Playback | undefined> {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return undefined;
  const voice = pickVoice(await browserVoices(), text);
  if (voice === undefined) return undefined;
  const utterance = new SpeechSynthesisUtterance(spokenText(text));
  utterance.voice = voice;
  utterance.lang = voice.lang;
  utterance.onend = onEnd;
  utterance.onerror = onEnd;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
  return { stop: () => window.speechSynthesis.cancel() };
}

/** Play an answer read by the server (MP3). Rejects when the server could not read it. */
export async function playFromServer(url: string, onEnd: () => void): Promise<Playback> {
  const audio = new Audio(url);
  audio.onended = onEnd;
  await audio.play();
  return {
    stop: () => {
      audio.pause();
      onEnd();
    },
  };
}

// ---- Recording for the server's recognition (Azure, see backend speech.py) ----

/** The sample rate Azure's short-audio recognition takes. */
export const RECOGNITION_RATE = 16_000;
/** Azure takes up to a minute; the recording stops by itself well before. */
export const MAX_RECORDING_MS = 30_000;

/** A 16-bit mono WAV file of `samples` (between -1 and 1), at `sampleRate`. */
export function encodeWav(samples: Float32Array, sampleRate: number = RECOGNITION_RATE): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset: number, text: string) => {
    for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index));
  };
  write(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, index) => {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  });
  return buffer;
}

/** Whether this browser can record the microphone (the server then recognises the speech). */
export function canRecord(): boolean {
  return (
    typeof navigator !== "undefined" &&
    navigator.mediaDevices?.getUserMedia !== undefined &&
    typeof MediaRecorder !== "undefined"
  );
}

/** Any browser's recording (WebM, MP4...) turned into 16 kHz mono WAV. */
async function toRecognitionWav(recording: Blob): Promise<ArrayBuffer> {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await recording.arrayBuffer());
    const frames = Math.ceil(decoded.duration * RECOGNITION_RATE);
    if (frames === 0) return encodeWav(new Float32Array(0));
    const offline = new OfflineAudioContext(1, frames, RECOGNITION_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return encodeWav(rendered.getChannelData(0));
  } finally {
    await context.close();
  }
}

export interface Recording {
  /** Stop recording and keep it: `done` gives the WAV file. */
  stop(): void;
  /** Stop recording and drop it: `done` gives undefined. */
  cancel(): void;
  /** The WAV file once recording has stopped (by `stop`, `cancel`, or the time limit). */
  done: Promise<ArrayBuffer | undefined>;
}

/** Record the microphone until stopped. Rejects when the browser refuses the microphone. */
export async function startRecording(): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  let cancelled = false;
  const finish = () => {
    if (recorder.state !== "inactive") recorder.stop();
  };
  const done = new Promise<ArrayBuffer | undefined>((resolve, reject) => {
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.onstop = () => {
      window.clearTimeout(limit);
      for (const track of stream.getTracks()) track.stop();
      if (cancelled) return resolve(undefined);
      toRecognitionWav(new Blob(chunks, { type: recorder.mimeType })).then(resolve, reject);
    };
  });
  recorder.start();
  const limit = window.setTimeout(finish, MAX_RECORDING_MS);
  return {
    stop: finish,
    cancel: () => {
      cancelled = true;
      finish();
    },
    done,
  };
}
