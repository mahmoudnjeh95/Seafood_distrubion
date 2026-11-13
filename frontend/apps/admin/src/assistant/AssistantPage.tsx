import {
  askAssistant,
  type Chat,
  type ChatMessage,
  dictateAssistant,
  getGetAssistantChatQueryKey,
  useGetAssistantChat,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { useTranslation } from "@frutti/i18n";
import { Button, Card, cn, EmptyState, Icon, PageHeader, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router";

import {
  canDictate,
  canRecord,
  dictate,
  type Dictation,
  DICTATION_LANGUAGES,
  type DictationLanguage,
  isWaiting,
  type Playback,
  playFromServer,
  type Recording,
  speakWithBrowser,
  startRecording,
} from "./speech";

const LANGUAGE_KEY = "frutti.assistant.dictation";
const READ_ALOUD_KEY = "frutti.assistant.readAloud";
// While a question waits for its answer the conversation is read again this often.
const POLL_MS = 1200;
const SUGGESTIONS = ["chnowa 3andi f frigo?", "chkoun ma khallasch?", "9addech bi3na lyoum?", "شنوة عندي في الكميون؟"];

function remembered(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function remember(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private browsing: the choice lasts until the page is closed.
  }
}

function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function speechUrl(message: ChatMessage): string {
  return `/api/v1/assistant/chat/messages/${message.id}/speech`;
}

function Bubble({
  message,
  playing,
  onListen,
}: {
  message: ChatMessage;
  playing: boolean;
  onListen: (message: ChatMessage) => void;
}) {
  const { t } = useTranslation();
  const mine = message.direction === "in";
  return (
    <div className={cn("flex max-w-[82%] flex-col gap-1 max-[860px]:max-w-[92%]", mine ? "self-end" : "self-start")}>
      <div
        dir="auto"
        className={cn(
          "rounded-[18px] px-4 py-2.5 text-[0.97rem] leading-relaxed break-words whitespace-pre-wrap",
          mine
            ? "rounded-ee-[6px] bg-sea text-surface"
            : "rounded-es-[6px] border border-line bg-surface-2 text-ink shadow-card",
        )}
      >
        {message.text}
      </div>
      <div className={cn("flex items-center gap-2 px-1 text-[0.72rem] text-ink-2", mine && "justify-end")}>
        <span className="num">{timeOf(message.created_at)}</span>
        {!mine && (
          <button
            type="button"
            onClick={() => onListen(message)}
            aria-pressed={playing}
            className={cn(
              "inline-flex items-center gap-1 rounded-chip px-1.5 py-0.5 font-semibold transition-colors hover:bg-surface-2 hover:text-ink",
              playing && "bg-sea-soft text-sea",
            )}
          >
            <Icon name={playing ? "stop" : "volume"} className="size-3.5" />
            {playing ? t("admin.assistant.stop") : t("admin.assistant.listen")}
          </button>
        )}
      </div>
    </div>
  );
}

function Thinking() {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      aria-label={t("admin.assistant.thinking")}
      className="flex items-center gap-1.5 self-start rounded-[18px] rounded-es-[6px] border border-line bg-surface-2 px-4 py-3.5"
    >
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-2 animate-bounce rounded-full bg-ink-2"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
  );
}

function Welcome({ name, onPick, disabled }: { name: string; onPick: (text: string) => void; disabled: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="m-auto flex max-w-[520px] flex-col items-center gap-4 py-6 text-center">
      <span className="grid size-16 place-items-center rounded-full bg-sea-soft text-sea">
        <Icon name="spark" className="size-8" />
      </span>
      <div>
        <h2 className="text-[1.35rem]">{t("admin.assistant.welcome", { name })}</h2>
        <p className="mt-1 text-ink-2">{t("admin.assistant.welcomeBody")}</p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            dir="auto"
            disabled={disabled}
            onClick={() => onPick(suggestion)}
            className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-[0.9rem] font-semibold text-ink transition-colors hover:border-sea hover:bg-sea-soft disabled:opacity-50"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * "Assistant IA" (D-314): the WhatsApp assistant inside the application, typed or dictated in Tunisian, Arabic or
 * French, with its answers read aloud. The worker answers; the screen reads the conversation until the answer is in.
 */
export function AssistantPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const queryClient = useQueryClient();
  const chatKey = getGetAssistantChatQueryKey();
  const chat = useGetAssistantChat({
    query: {
      refetchInterval: (query) => (query.state.data && isWaiting(query.state.data.messages) ? POLL_MS : false),
    },
  });
  const messages = chat.data?.messages;
  const enabled = chat.data?.enabled ?? false;
  const serverVoice = chat.data?.server_voice ?? false;
  const waiting = messages !== undefined && isWaiting(messages);

  const [draft, setDraft] = useState("");
  const [listening, setListening] = useState(false);
  const [language, setLanguage] = useState<DictationLanguage>(() =>
    remembered(LANGUAGE_KEY) === "fr-FR" ? "fr-FR" : "ar-TN",
  );
  const [readAloud, setReadAloud] = useState(() => remembered(READ_ALOUD_KEY) === "1");
  const [playingId, setPlayingId] = useState<number | null>(null);
  const [transcribing, setTranscribing] = useState(false);
  const dictation = useRef<Dictation | undefined>(undefined);
  const recorder = useRef<Recording | undefined>(undefined);
  const playback = useRef<Playback | undefined>(undefined);
  // The answers already there when the screen opened are not read aloud; only the ones that come after.
  const lastHeard = useRef<number | null>(null);
  const lastQuestionSpoken = useRef(false);
  const warnedNoVoice = useRef(false);
  const end = useRef<HTMLDivElement>(null);
  // The server's recognition (Azure, with the key) understands Tunisian on any browser that records; otherwise the
  // browser's own recognition (Chrome and Edge) does the job.
  const serverDictation = serverVoice && canRecord();
  const dictationAvailable = serverDictation || canDictate();

  const stopPlayback = useCallback(() => {
    playback.current?.stop();
    playback.current = undefined;
    setPlayingId(null);
  }, []);

  const listen = useCallback(
    async (message: ChatMessage) => {
      stopPlayback();
      setPlayingId(message.id);
      const done = () => setPlayingId((current) => (current === message.id ? null : current));
      if (serverVoice) {
        try {
          playback.current = await playFromServer(speechUrl(message), done);
          return;
        } catch {
          // The server's voice failed: the browser's own, below.
        }
      }
      const spoken = await speakWithBrowser(message.text, done);
      if (spoken === undefined) {
        done();
        if (!warnedNoVoice.current) toast.info(t("admin.assistant.noVoice"));
        warnedNoVoice.current = true;
        return;
      }
      playback.current = spoken;
    },
    [serverVoice, stopPlayback, t],
  );

  const ask = useMutation({
    mutationFn: (question: { text: string; spoken: boolean }) => askAssistant(question),
    onSuccess: (created) => {
      queryClient.setQueryData<Chat>(chatKey, (old) =>
        old ? { ...old, messages: [...old.messages.filter((message) => message.id !== created.id), created] } : old,
      );
      void queryClient.invalidateQueries({ queryKey: chatKey });
    },
    onError: () => toast.error(t("admin.assistant.notSent")),
  });
  const busy = waiting || ask.isPending;

  const send = (text: string, dictated: boolean) => {
    const question = text.trim();
    if (question === "" || busy || !enabled) return;
    stopPlayback();
    lastQuestionSpoken.current = dictated || readAloud;
    setDraft("");
    ask.mutate({ text: question, spoken: lastQuestionSpoken.current });
  };

  const startServerListening = async () => {
    stopPlayback();
    setDraft("");
    let recording: Recording;
    try {
      recording = await startRecording();
    } catch (error) {
      const refused = error instanceof DOMException && error.name === "NotAllowedError";
      toast.error(t(`admin.assistant.dictation.${refused ? "denied" : "failed"}`));
      return;
    }
    recorder.current = recording;
    setListening(true);
    recording.done
      .then(async (wav) => {
        recorder.current = undefined;
        setListening(false);
        if (wav === undefined) return;
        setTranscribing(true);
        try {
          const heard = await dictateAssistant({ language }, new Blob([wav], { type: "audio/wav" }));
          if (heard.text.trim() === "") toast.error(t("admin.assistant.dictation.silent"));
          else send(heard.text, true);
        } catch {
          toast.error(t("admin.assistant.dictation.failed"));
        } finally {
          setTranscribing(false);
        }
      })
      .catch(() => {
        recorder.current = undefined;
        setListening(false);
        toast.error(t("admin.assistant.dictation.failed"));
      });
  };

  const stopListening = () => {
    if (recorder.current !== undefined) recorder.current.stop();
    else dictation.current?.stop();
  };

  const startListening = () => {
    if (serverDictation) {
      void startServerListening();
      return;
    }
    stopPlayback();
    setDraft("");
    dictation.current = dictate({
      language,
      onHeard: setDraft,
      onDone: (text) => {
        setListening(false);
        send(text, true);
      },
      onFailure: (failure) => {
        setListening(false);
        toast.error(t(`admin.assistant.dictation.${failure}`));
      },
    });
    setListening(dictation.current !== undefined);
  };

  const cancelListening = () => {
    dictation.current?.cancel();
    recorder.current?.cancel();
    setListening(false);
    setDraft("");
  };

  // A new answer: bring it into view, and read it aloud when the question was dictated or reading aloud is on.
  const last = messages?.at(-1);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
    if (last === undefined) {
      if (messages !== undefined) lastHeard.current = 0;
      return;
    }
    const firstLoad = lastHeard.current === null;
    const fresh = !firstLoad && last.direction === "out" && last.id > (lastHeard.current ?? 0);
    lastHeard.current = last.id;
    if (fresh && lastQuestionSpoken.current) void listen(last);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a new last message matters
  }, [last?.id, messages === undefined]);

  useEffect(
    () => () => {
      dictation.current?.cancel();
      recorder.current?.cancel();
      playback.current?.stop();
    },
    [],
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    send(draft, false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send(draft, false);
    }
  };

  const name = session.user.first_name || session.user.username;

  return (
    <div className="flex h-[calc(100dvh-150px)] min-h-[480px] flex-col gap-4">
      <PageHeader eyebrow={t("admin.groups.assistant")} title={t("admin.assistant.title")}>
        <div
          role="radiogroup"
          aria-label={t("admin.assistant.dictationLanguage")}
          className="inline-flex rounded-control border border-line bg-surface p-0.5"
        >
          {DICTATION_LANGUAGES.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={language === option}
              onClick={() => {
                setLanguage(option);
                remember(LANGUAGE_KEY, option);
              }}
              className={cn(
                "rounded-[8px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2 transition-colors",
                language === option && "bg-sea-soft text-sea",
              )}
            >
              {t(`admin.assistant.languages.${option}`)}
            </button>
          ))}
        </div>
        <Button
          aria-pressed={readAloud}
          onClick={() => {
            if (readAloud) stopPlayback();
            setReadAloud(!readAloud);
            remember(READ_ALOUD_KEY, readAloud ? "0" : "1");
          }}
          className={cn(readAloud && "border-sea bg-sea-soft text-sea hover:bg-sea-soft")}
        >
          <Icon name="volume" />
          {readAloud ? t("admin.assistant.readAloudOn") : t("admin.assistant.readAloudOff")}
        </Button>
      </PageHeader>

      {chat.isError ? (
        <EmptyState illustration="mix" title={t("admin.assistant.loadError")}>
          {t("common.serverUnreachable")}
        </EmptyState>
      ) : (
        <Card className="flex min-h-0 flex-1 flex-col overflow-hidden p-0">
          {chat.data && !enabled && (
            <p className="border-b border-line bg-warn-soft px-5 py-2.5 text-[0.9rem] font-semibold text-warn">
              {t("admin.assistant.disabled")}
            </p>
          )}
          <div aria-live="polite" className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-5 py-5">
            {messages === undefined ? (
              <p className="m-auto text-ink-2">{t("common.loading")}</p>
            ) : messages.length === 0 ? (
              <Welcome name={name} onPick={(text) => send(text, false)} disabled={busy || !enabled} />
            ) : (
              messages.map((message) => (
                <Bubble
                  key={message.id}
                  message={message}
                  playing={playingId === message.id}
                  onListen={(target) => (playingId === target.id ? stopPlayback() : void listen(target))}
                />
              ))
            )}
            {busy && <Thinking />}
            <div ref={end} />
          </div>

          {listening && (
            <div className="flex items-center gap-3 border-t border-line bg-coral-soft px-5 py-2 text-[0.9rem]">
              <span className="relative flex size-2.5">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-coral opacity-70" />
                <span className="relative inline-flex size-2.5 rounded-full bg-coral" />
              </span>
              <span className="flex-1 font-semibold text-ink">{t("admin.assistant.listening")}</span>
              <button type="button" onClick={cancelListening} className="font-semibold text-ink-2 hover:text-ink">
                {t("common.cancel")}
              </button>
            </div>
          )}

          <form onSubmit={submit} className="flex items-end gap-2.5 border-t border-line bg-surface p-3">
            <textarea
              dir="auto"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
              readOnly={listening}
              disabled={!enabled}
              rows={Math.min(4, Math.max(1, draft.split("\n").length))}
              maxLength={2000}
              placeholder={listening ? t("admin.assistant.speakNow") : t("admin.assistant.placeholder")}
              aria-label={t("admin.assistant.placeholder")}
              className="min-h-12 flex-1 resize-none rounded-[14px] border border-line bg-surface-2 px-4 py-3 text-[0.97rem] text-ink placeholder:text-ink-2 focus-visible:border-sea focus-visible:outline-none disabled:opacity-60"
            />
            <button
              type="button"
              onClick={() => (listening ? stopListening() : startListening())}
              disabled={!dictationAvailable || !enabled || busy || transcribing}
              aria-pressed={listening}
              aria-label={listening ? t("admin.assistant.micStop") : t("admin.assistant.micStart")}
              title={
                dictationAvailable
                  ? listening
                    ? t("admin.assistant.micStop")
                    : t("admin.assistant.micStart")
                  : t("admin.assistant.micUnsupported")
              }
              className={cn(
                "relative grid size-12 flex-none place-items-center rounded-full border transition-[filter,background-color] disabled:opacity-40",
                listening
                  ? "border-coral bg-coral text-white"
                  : "border-coral bg-coral-soft text-coral hover:brightness-105",
              )}
            >
              {listening && <span className="absolute inset-0 animate-ping rounded-full bg-coral opacity-30" />}
              <Icon name={listening ? "stop" : "mic"} className="relative size-[22px]" />
            </button>
            <button
              type="submit"
              disabled={draft.trim() === "" || busy || listening || !enabled}
              aria-label={t("admin.assistant.send")}
              title={t("admin.assistant.send")}
              className="grid size-12 flex-none place-items-center rounded-full border border-sea bg-sea text-surface transition-[filter] hover:brightness-110 disabled:opacity-40"
            >
              <Icon name="send" className="size-[20px] rtl:-scale-x-100" />
            </button>
          </form>
          {!dictationAvailable && (
            <p className="border-t border-line bg-surface-2 px-5 py-2 text-[0.8rem] text-ink-2">
              {t("admin.assistant.micUnsupported")}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
