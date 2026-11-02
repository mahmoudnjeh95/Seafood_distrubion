import { describe, expect, it } from "vitest";

import { amountLeft, dueDateOn, lineAmount, purchaseTotals } from "./purchase";
import { decisionsToRead } from "./purchaseWatch";

describe("lineAmount", () => {
  it("multiplies kg by the price and rounds half up to the millime", () => {
    expect(lineAmount("30", "25")).toBe("750.000");
    expect(lineAmount("6,5", "16,250")).toBe("105.625");
    expect(lineAmount("0,333", "1,5")).toBe("0.500");
  });

  it("waits for a readable weight above zero", () => {
    expect(lineAmount("", "25")).toBeNull();
    expect(lineAmount("0", "25")).toBeNull();
    expect(lineAmount("12", "")).toBeNull();
  });
});

describe("purchaseTotals", () => {
  it("adds the lines and the sums given, and never shows a negative rest", () => {
    expect(
      purchaseTotals(
        [
          { kilos: "30", price: "25" },
          { kilos: "", price: "" },
        ],
        ["600", ""],
      ),
    ).toEqual({
      total: "750.000",
      paid: "600.000",
      rest: "150.000",
      overpaid: false,
    });
    const over = purchaseTotals([{ kilos: "10", price: "8,5" }], ["50", "100"]);
    expect(over.rest).toBe("0.000");
    expect(over.overpaid).toBe(true);
    expect(purchaseTotals([{ kilos: "10", price: "8,5" }], ["85"]).overpaid).toBe(false);
  });
});

describe("dueDateOn", () => {
  it("follows the deal", () => {
    expect(dueDateOn("2026-10-15", "cash", 0)).toBe("2026-10-15");
    expect(dueDateOn("2026-10-15", "days", 15)).toBe("2026-10-30");
    expect(dueDateOn("2026-10-15", "month_end", 0)).toBe("2026-10-31");
  });
});

describe("decisionsToRead", () => {
  const now = Date.parse("2026-10-16T10:00:00Z");
  const purchase = (id: number, status: "submitted" | "validated" | "refused", decidedAt: string | null) =>
    ({ id, status, decided_at: decidedAt }) as Parameters<typeof decisionsToRead>[0][number];

  it("keeps the recent decisions not read yet", () => {
    const rows = [
      purchase(1, "submitted", null),
      purchase(2, "validated", "2026-10-16T09:00:00Z"),
      purchase(3, "refused", "2026-10-15T09:00:00Z"),
      purchase(4, "validated", "2026-10-01T09:00:00Z"),
    ];
    expect(decisionsToRead(rows, [3], now).map((row) => row.id)).toEqual([2]);
  });
});

describe("amountLeft", () => {
  it("is the total minus what was paid, never below zero", () => {
    expect(amountLeft("130.000", "100")).toBe("30.000");
    expect(amountLeft("130", "130.000")).toBe("0.000");
    expect(amountLeft("50", "80")).toBe("0.000");
  });
});
