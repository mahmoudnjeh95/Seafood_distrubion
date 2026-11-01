import { describe, expect, test } from "vitest";

import { cashOffOn, paidWithOn } from "./expensePaid";

describe("La caisse on the phone (D-220)", () => {
  test("a day started with 0 DT, or not started, has no cash to pay from", () => {
    expect(cashOffOn("0.000")).toBe(true);
    expect(cashOffOn(undefined)).toBe(true);
  });

  test("a day started with some cash can pay from the box", () => {
    expect(cashOffOn("50.000")).toBe(false);
    expect(cashOffOn("0.001")).toBe(false);
  });

  test("while the box is off, the cash choice falls back to Ma poche; the other choices stay", () => {
    expect(paidWithOn("cash", true)).toBe("pocket");
    expect(paidWithOn("card", true)).toBe("card");
    expect(paidWithOn("pocket", true)).toBe("pocket");
    expect(paidWithOn("cash", false)).toBe("cash");
  });
});
