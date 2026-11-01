import { expect, test } from "vitest";

import { formatMoneyInput, moneyInputCaret, parseDecimalInput } from "./index";

// Intl's thousands separator is a no-break space: the tests compare with a plain space.
const shown = (typed: string) => formatMoneyInput(typed).replace(/\s/g, " ");

test("typed amounts get thousands separators and keep the decimal comma", () => {
  expect(shown("1250")).toBe("1 250");
  expect(shown("1250,5")).toBe("1 250,5");
  expect(shown("1250000")).toBe("1 250 000");
  expect(shown("99999999999.999")).toBe("99 999 999 999,999");
});

test("a dot is read as the decimal comma, and the decimals are not cut", () => {
  expect(shown("1250.5")).toBe("1 250,5");
  // More than 3 decimals are still shown: parseDecimalInput refuses them, as before.
  expect(shown("1250,1234")).toBe("1 250,1234");
  expect(parseDecimalInput(formatMoneyInput("1250,1234"), 3)).toBeNull();
});

test("the empty text, a sign, a lone comma and leading zeros", () => {
  expect(shown("")).toBe("");
  expect(shown("-")).toBe("-");
  expect(shown("-42")).toBe("-42");
  expect(shown("0")).toBe("0");
  expect(shown("0005")).toBe("5");
  expect(shown("0,5")).toBe("0,5");
});

test("pasted text with spaces or no-break spaces is read as the amount", () => {
  expect(shown("1 250,5")).toBe("1 250,5");
  expect(shown("1 250 000")).toBe("1 250 000");
});

test("a second decimal separator is ignored", () => {
  expect(shown("1.250.000")).toBe("1,250000");
});

test("formatting a formatted amount changes nothing", () => {
  for (const typed of ["1250", "1250,5", "-7,125", "0,5", "1 250 000,123", ""]) {
    const once = formatMoneyInput(typed);
    expect(formatMoneyInput(once)).toBe(once);
  }
});

test("what is shown reads back as the decimal string the API expects", () => {
  expect(parseDecimalInput(formatMoneyInput("1250,5"), 3)).toBe("1250.5");
  expect(parseDecimalInput(formatMoneyInput("1250000"), 3)).toBe("1250000");
  expect(parseDecimalInput(formatMoneyInput("1250.500"), 3)).toBe("1250.500");
});

test("the caret stays after the digits that were before it", () => {
  // Typing 5 at the start of "1 250" → "51 250", the caret after the 5.
  expect(moneyInputCaret("51250", 1, formatMoneyInput("51250"))).toBe(1);
  // Typing a digit at the end: "1 250" + "0" → "1 2500" → "12 500", the caret at the end.
  expect(moneyInputCaret("1 2500", 6, formatMoneyInput("1 2500"))).toBe(6);
  // The comma typed after the whole part stays before the caret: "1250," with the caret after the comma.
  expect(moneyInputCaret("1250,", 5, formatMoneyInput("1250,"))).toBe(6);
  // The caret at the start or after the first digit of "12 500".
  expect(moneyInputCaret("12500", 1, formatMoneyInput("12500"))).toBe(1);
  expect(moneyInputCaret("12500", 0, formatMoneyInput("12500"))).toBe(0);
});
