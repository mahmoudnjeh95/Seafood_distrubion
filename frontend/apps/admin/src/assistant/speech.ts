// The voice of the "Assistant IA" screen (D-310): dictation and reading aloud with what the browser offers.
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
