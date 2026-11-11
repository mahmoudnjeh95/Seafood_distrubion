import { expect, test } from "vitest";

import { ANSWER_WAIT_MS, isArabic, isWaiting, pickVoice, spokenText } from "./speech";

const voice = (lang: string, name: string) => ({ lang, name });

test("an answer in Arabic letters gets the Tunisian voice, then any Arabic one", () => {
  const voices = [
    voice("fr-FR", "Google français"),
    voice("ar-SA", "Microsoft Naayf"),
    voice("ar-TN", "Microsoft Hedi Online (Natural)"),
  ];
  expect(pickVoice(voices, "عندك 12 كيلو")?.lang).toBe("ar-TN");
  expect(pickVoice(voices.slice(0, 2), "عندك 12 كيلو")?.lang).toBe("ar-SA");
  expect(pickVoice(voices.slice(0, 1), "عندك 12 كيلو")).toBeUndefined();
});

test("an answer in Latin letters gets a French voice, the natural one first", () => {
  const voices = [
    voice("en-US", "Google US English"),
    voice("fr_FR", "Microsoft Hortense"),
    voice("fr-FR", "Microsoft Denise Online (Natural)"),
  ];
  expect(pickVoice(voices, "Vous avez 12 kg")?.name).toBe("Microsoft Denise Online (Natural)");
  expect(pickVoice(voices.slice(0, 2), "3andek 12 kg")?.name).toBe("Microsoft Hortense");
});

test("Arabic letters are recognised inside a mixed sentence", () => {
  expect(isArabic("stock: 12 كيلو")).toBe(true);
  expect(isArabic("3andek 12 kg 9ar3oun")).toBe(false);
});

test("the screen waits for an answer only after a recent question", () => {
  const now = Date.parse("2026-11-10T10:00:00Z");
  const at = (direction: string, minutesAgo: number) => ({
    direction,
    created_at: new Date(now - minutesAgo * 60_000).toISOString(),
  });
  expect(isWaiting([], now)).toBe(false);
  expect(isWaiting([at("in", 1)], now)).toBe(true);
  expect(isWaiting([at("in", 2), at("out", 1)], now)).toBe(false);
  expect(isWaiting([at("in", ANSWER_WAIT_MS / 60_000 + 1)], now)).toBe(false);
});

test("the voice does not read the marks of a written answer", () => {
  expect(spokenText("**Stock**\n- 12 kg `crevette`\n• 3 kg")).toBe("Stock\n12 kg crevette\n3 kg");
});
