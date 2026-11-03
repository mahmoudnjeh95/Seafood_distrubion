import { afterEach, expect, test } from "vitest";

import {
  applyLanguage,
  formatDate,
  formatDateTime,
  formatMoney,
  formatPercent,
  formatQuantity,
  formatTemperature,
  i18n,
  parseDecimalInput,
} from "./index";

afterEach(() => applyLanguage("fr"));

test("French is the default language and reads left to right", () => {
  applyLanguage("fr");

  expect(i18n.t("auth.title")).toBe("Connexion");
  expect(document.documentElement.lang).toBe("fr");
  expect(document.documentElement.dir).toBe("ltr");
});

test("Arabic switches the page to right-to-left and falls back to French for missing texts", () => {
  applyLanguage("ar");

  expect(document.documentElement.lang).toBe("ar");
  expect(document.documentElement.dir).toBe("rtl");
  expect(i18n.t("auth.title")).toBe("ادخل");
  expect(i18n.t("truck.tabs.sale")).toBe("البيع");
  // A text with no Arabic yet shows the French one.
  expect(i18n.t("admin.nav.dashboard")).toBe("Tableau de bord");
});

test("texts take values", () => {
  expect(i18n.t("admin.dashboard.hello", { name: "Nadia" })).toBe("Bonjour Nadia");
});

test("amounts show three decimals, grouped thousands and the currency", () => {
  expect(formatMoney("1250")).toMatch(/^1\s250,000\sDT$/);
  expect(formatMoney("0.5")).toMatch(/^0,500\sDT$/);
  expect(formatMoney("-42.125")).toMatch(/^-42,125\sDT$/);
  expect(formatMoney("1250", "ar")).toMatch(/^1\.250,000\sد\.ت$/);
});

test("large amounts keep every millime", () => {
  // As a JavaScript number this would lose its last digit.
  expect(formatMoney("99999999999.999")).toMatch(/^99\s999\s999\s999,999\sDT$/);
  expect(formatMoney("9007199254740993.001")).toMatch(/993,001\sDT$/);
});

test("weights show three decimals and the unit", () => {
  expect(formatQuantity("12.5")).toMatch(/^12,500\skg$/);
});

test("numbers that are not decimal strings are refused", () => {
  expect(() => formatMoney("12,5")).toThrow(TypeError);
  expect(() => formatMoney("")).toThrow(TypeError);
  expect(() => formatMoney("1e3")).toThrow(TypeError);
});

test("dates are written day/month/year", () => {
  expect(formatDate("2026-10-09")).toBe("09/10/2026");
  expect(formatDate("2026-01-05")).toBe("05/01/2026");
});

test("a timestamp is shown on its Tunisian date", () => {
  // 23:30 UTC on the 9th is already 00:30 on the 10th in Tunis.
  expect(formatDate("2026-10-09T23:30:00Z")).toBe("10/10/2026");
  expect(() => formatDate("hier")).toThrow(TypeError);
});

test("a timestamp is shown with its Tunisian time", () => {
  // 13:05 UTC is 14:05 in Tunis (UTC+1, no summer time).
  expect(formatDateTime("2026-10-09T13:05:00Z", "fr")).toBe("09/10/2026 14:05");
});

test("temperatures show at most one decimal", () => {
  expect(formatTemperature("-18.0", "fr")).toBe("-18\u00a0°C");
  expect(formatTemperature("2.5", "fr")).toBe("2,5\u00a0°C");
});

test.each([
  ["42", "42"],
  ["42,5", "42.5"],
  ["42.500", "42.500"],
  [" 1 250,750 ", "1250.750"],
  ["1\u202f250,5", "1250.5"],
  ["-18", "-18"],
  ["3\u066b5", "3.5"],
])("typed number %j is read as %j", (typed, expected) => {
  expect(parseDecimalInput(typed, 3)).toBe(expected);
});

test.each(["", "abc", "1.2345", "1,2,3", ",5", "1e3", "12 kg"])("typed text %j is not a number", (typed) => {
  expect(parseDecimalInput(typed, 3)).toBeNull();
});

test("a change in percent carries its sign and one decimal", () => {
  expect(formatPercent("1.3")).toMatch(/^\+1,3\s%$/);
  expect(formatPercent("-10.0")).toMatch(/^-10,0\s%$/);
  expect(formatPercent("0.0")).toMatch(/^0,0\s%$/);
});
