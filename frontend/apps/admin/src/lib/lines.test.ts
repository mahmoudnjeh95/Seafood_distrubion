import { expect, test } from "vitest";

import { amountsOf, filled, isBlank, isShort, netUnderMinimum, newLine, shownPrice, withSpare } from "./lines";

test("a row is blank until a product is chosen or something is typed", () => {
  expect(isBlank(newLine())).toBe(true);
  expect(isBlank(newLine({ quantity: " " }))).toBe(true);
  expect(isBlank(newLine({ product: "4" }))).toBe(false);
  expect(isBlank(newLine({ quantity: "2" }))).toBe(false);
  expect(isBlank(newLine({ unit_price: "7,5", priceTouched: true }))).toBe(false);
  expect(isBlank(newLine({ discount_rate: "5" }))).toBe(false);
});

test("the grid always ends with one blank row, and only one", () => {
  const sardine = newLine({ product: "4", quantity: "2" });
  const typed = withSpare([sardine]);
  expect(typed).toHaveLength(2);
  expect(typed[0]).toBe(sardine);
  expect(isBlank(typed[1]!)).toBe(true);

  // Already ending with its blank row: the same rows, untouched.
  expect(withSpare(typed)).toBe(typed);

  // A row emptied above the spare one stays (the person is in it); the row after it goes.
  const emptied = newLine();
  expect(withSpare([sardine, emptied, newLine()])).toEqual([sardine, emptied]);
  expect(withSpare([])).toHaveLength(1);
});

test("blank rows are not sent: only the filled ones count, in their order", () => {
  const sardine = newLine({ product: "4" });
  const poulpe = newLine({ product: "6" });
  expect(filled([sardine, newLine(), poulpe, newLine()])).toEqual([sardine, poulpe]);
});

test("a row shows the price in force until a price is typed", () => {
  expect(shownPrice(newLine({ product: "4" }), "7.500")).toBe("7,500");
  expect(shownPrice(newLine({ product: "4" }), null)).toBe("");
  expect(shownPrice(newLine({ product: "4", unit_price: "8", priceTouched: true }), "7.500")).toBe("8");
  expect(shownPrice(newLine({ product: "4", unit_price: "", priceTouched: true }), "7.500")).toBe("");
});

test("a row's amount is its kilos at its price, less its discount, as the server computes it", () => {
  // 4 × 22.500 = 90.000, less 10 % = 81.000
  expect(amountsOf(newLine({ quantity: "4", discount_rate: "10" }), "22,500")).toEqual({
    gross: "90.000",
    discount: "9.000",
    amount: "81.000",
  });
  expect(amountsOf(newLine({ quantity: "1,5" }), "14")?.amount).toBe("21.000");
  expect(amountsOf(newLine({ quantity: "" }), "14")).toBeNull();
  expect(amountsOf(newLine({ quantity: "2" }), "")).toBeNull();
  expect(amountsOf(newLine({ quantity: "-2" }), "14")).toBeNull();
  expect(amountsOf(newLine({ quantity: "2", discount_rate: "abc" }), "14")).toBeNull();
});

test("more kilos typed than the place holds is short; an unknown stock never is", () => {
  expect(isShort("5,001", "5.000")).toBe(true);
  expect(isShort("5", "5.000")).toBe(false);
  expect(isShort("0,2", "0")).toBe(true);
  expect(isShort("abc", "5.000")).toBe(false);
  expect(isShort("5000", undefined)).toBe(false);
});

test("a price after the discount under the product's minimum is named; no minimum never warns", () => {
  const discounted = newLine({ product: "4", discount_rate: "10" });
  expect(netUnderMinimum(discounted, "42,000", "40.000")).toBe("37.800");
  expect(netUnderMinimum(newLine({ product: "4", discount_rate: "5" }), "42,000", "40.000")).toBeNull();
  expect(netUnderMinimum(newLine({ product: "4" }), "38,000", "40.000")).toBe("38.000");
  expect(netUnderMinimum(discounted, "42,000", null)).toBeNull();
  expect(netUnderMinimum(discounted, "", "40.000")).toBeNull();
});
