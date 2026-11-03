import { describe, expect, test } from "vitest";

import { encodeText, escposJob, rasterJob, toBits } from "./escpos";
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
  test("a line without a unit price prints the kilos only", () => {
    const rows = layoutReceipt(
      { ...SALE, number: "Provisoire", lines: [{ name: "Loup", quantity: "2.5", amount: "75" }] },
      "party",
      32,
    );
    const text = previewText(rows, 32);
    expect(text).toContain("2,500");
    expect(text).toContain("75,000");
    expect(text).not.toContain(" x ");
    expect(text).toContain("Provisoire");
  });

  test("the seller's address, phone and matricule fiscal head the paper, the driver signs it at the bottom", () => {
    const text = previewText(
      layoutReceipt(
        { ...SALE, by: "Ahmed", seller: { address: "Sakiet Ezzit, Sfax", phone: "74 000 000", taxId: "1234567A" } },
        "party",
        32,
      ),
      32,
    );
    const lines = text.split("\n").map((line) => line.trim());
    expect(lines.slice(0, 4)).toEqual(["Frutti Del Mare", "Sakiet Ezzit, Sfax", "Tél : 74 000 000", "MF : 1234567A"]);
    expect(lines).toContain("Préparé par : Ahmed");
    expect(text).toMatch(/Heure\s+\d\d:\d\d/);
  });

  test("the goods are a table of kilos, price and amount", () => {
    const narrow = previewText(layoutReceipt(SALE, "party", 32), 32).split("\n");
    expect(narrow).toContain("     4,000    32,500     130,000");
    const wide = previewText(layoutReceipt(SALE, "party", 48), 48).split("\n");
    expect(wide.some((line) => line.startsWith("Article") && line.endsWith("Montant"))).toBe(true);
    expect(wide.some((line) => line.startsWith("Crevettes") && line.endsWith("130,000"))).toBe(true);
  });

  test("a huge amount that does not fit the columns still stays on the paper", () => {
    const big = {
      ...SALE,
      lines: [{ name: "Thon", quantity: "123456.5", unitPrice: "123456.5", amount: "15241507232" }],
    };
    for (const line of previewText(layoutReceipt(big, "party", 32), 32).split("\n"))
      expect(line.length).toBeLessThanOrEqual(32);
  });

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
    expect(party).not.toContain("COPIE BUREAU");
    // Marked at the top, so the two papers are never mixed up.
    expect(office.indexOf("COPIE BUREAU")).toBeLessThan(office.indexOf("Client"));
    expect(office).toContain("Signature client");
    expect(party).toContain("Reste à payer");
    expect(previewText(layoutReceipt({ ...SALE, rest: "0" }, "party", 42), 42)).not.toContain("Reste à payer");
  });

  test("a purchase receipt names the supplier", () => {
    expect(previewText(layoutReceipt({ ...SALE, kind: "purchase" }, "office", 42), 42)).toContain("Fournisseur");
  });
});

describe("Arabic names and the logo (D-282)", () => {
  const withArabic: ReceiptData = { ...SALE, lines: [{ ...SALE.lines[0]!, nameAr: "قمبري مقشّر" }] };

  test("the Arabic name follows the French one, the logo heads the paper", () => {
    const rows = layoutReceipt(withArabic, "party", 32);
    expect(rows[0]).toEqual({ logo: true });
    const at = rows.findIndex((row) => "ar" in row && row.ar);
    expect(rows[at]).toEqual({ text: "قمبري مقشّر", align: "right", ar: true });
    expect(rows[at - 1]).toMatchObject({ text: "21/25" });
    expect(previewText(rows, 32)).toContain("قمبري مقشّر");
  });

  test("the text mode prints neither the Arabic nor the logo", () => {
    const text = escposJob([layoutReceipt(withArabic, "party", 32)], { cols: 32, accents: true });
    const plain = escposJob([layoutReceipt(SALE, "party", 32)], { cols: 32, accents: true });
    expect([...text]).toEqual([...plain]);
  });

  test("a picture is sent as dots, one bit each, then cut", () => {
    // 16 dots wide, 2 rows: the first row black, the second white.
    const rgba = new Uint8ClampedArray(16 * 2 * 4);
    for (let i = 0; i < 16; i += 1) rgba.set([0, 0, 0, 255], i * 4);
    for (let i = 16; i < 32; i += 1) rgba.set([255, 255, 255, 255], i * 4);
    const bitmap = toBits(rgba, 16, 2);
    expect([...bitmap.bits]).toEqual([0xff, 0xff, 0, 0]);
    const bytes = [...rasterJob([bitmap])];
    expect(bytes.slice(0, 10)).toEqual([0x1b, 0x40, 0x1d, 0x76, 0x30, 0, 2, 0, 2, 0]);
    expect(bytes.slice(10, 14)).toEqual([0xff, 0xff, 0, 0]);
    expect(bytes.slice(-4)).toEqual([0x1d, 0x56, 0x42, 0x00]);
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
