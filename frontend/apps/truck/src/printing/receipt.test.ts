import { describe, expect, test } from "vitest";

import { encodeText, escposJob } from "./escpos";
import { amount, layoutReceipt, previewText, type ReceiptData, twoColumns, wrap } from "./receipt";

const SALE: ReceiptData = {
  kind: "sale",
  company: "Frutti Del Mare",
  number: "VE-1",
  date: "2026-11-02T09:41:00Z",
  partyName: "Restaurant Le Corail",
  lines: [{ name: "Crevettes décortiquées calibre 21/25", quantity: "4", unitPrice: "32.5", amount: "130" }],
  total: "130",
  paid: "100",
  rest: "30",
};

describe("receipt layout", () => {
  test("amounts keep three decimals and group thousands", () => {
    expect(amount("1250")).toBe("1 250,000");
    expect(amount("0.5")).toBe("0,500");
    expect(amount("-12.3456")).toBe("-12,346");
  });

  test("two columns fill the line exactly, and cut the left text if needed", () => {
    expect(twoColumns("Total", "10,000", 20)).toHaveLength(20);
    expect(twoColumns("A very long product name", "10,000", 20)).toHaveLength(20);
  });

  test("wrap never exceeds the width", () => {
    for (const line of wrap("Crevettes décortiquées calibre 21/25 extra-large", 16))
      expect(line.length).toBeLessThanOrEqual(16);
  });

  test.each([32, 42, 48])("no line is wider than %i columns", (cols) => {
    for (const copy of ["party", "office"] as const) {
      const text = previewText(layoutReceipt(SALE, copy, cols), cols);
      for (const line of text.split("\n")) expect(line.length).toBeLessThanOrEqual(cols);
    }
  });

  test("only the office copy has the signature line; the rest shows only when something is owed", () => {
    const party = previewText(layoutReceipt(SALE, "party", 42), 42);
    const office = previewText(layoutReceipt(SALE, "office", 42), 42);
    expect(party).not.toContain("Signature");
    expect(office).toContain("COPIE BUREAU");
    expect(office).toContain("Signature client");
    expect(party).toContain("Reste à payer");
    expect(previewText(layoutReceipt({ ...SALE, rest: "0" }, "party", 42), 42)).not.toContain("Reste à payer");
  });

  test("a purchase receipt names the supplier", () => {
    expect(previewText(layoutReceipt({ ...SALE, kind: "purchase" }, "office", 42), 42)).toContain("Fournisseur");
  });
});

describe("ESC/POS", () => {
  test("French accents use code page 858, or are dropped when accents are off", () => {
    expect(encodeText("é à ç", true)).toEqual([0x82, 0x20, 0x85, 0x20, 0x87]);
    expect(encodeText("é à ç", false)).toEqual([0x65, 0x20, 0x61, 0x20, 0x63]);
  });

  test("a job starts with a reset and ends with a cut for each copy", () => {
    const bytes = escposJob([layoutReceipt(SALE, "party", 42), layoutReceipt(SALE, "office", 42)], {
      cols: 42,
      accents: true,
    });
    expect([...bytes.slice(0, 2)]).toEqual([0x1b, 0x40]);
    const cuts = [...bytes].reduce((n, byte, i) => (byte === 0x1d && bytes[i + 1] === 0x56 ? n + 1 : n), 0);
    expect(cuts).toBe(2);
  });
});
