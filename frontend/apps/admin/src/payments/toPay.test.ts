import { expect, test } from "vitest";

import { amountToPay, creditHeld } from "./toPay";

test("the amount to pay is the positive balance, zero for a credit", () => {
  expect(amountToPay("70.000")).toBe("70.000");
  expect(amountToPay("0.001")).toBe("0.001");
  expect(amountToPay("-20.000")).toBe("0.000");
  expect(amountToPay("0.000")).toBe("0.000");
});

test("a negative balance is the credit held, to the millime", () => {
  expect(creditHeld("-20.000")).toBe("20.000");
  expect(creditHeld("-0.500")).toBe("0.500");
  expect(creditHeld("70.000")).toBe("0.000");
});
