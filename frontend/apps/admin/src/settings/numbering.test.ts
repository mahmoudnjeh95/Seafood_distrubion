import type { NumberLine } from "@frutti/api";
import { expect, test } from "vitest";

import { nextWithPrefix } from "./numbering";

const invoice: NumberLine = {
  kind: "invoice",
  title: "Facture",
  group: "Ventes",
  prefix: "FA",
  default_prefix: "FA",
  yearly: true,
  next_number: "FA-2026-0008",
};

test("the preview reads with the prefix typed, the year and the number kept", () => {
  expect(nextWithPrefix(invoice, "FACT")).toBe("FACT-2026-0008");
  expect(nextWithPrefix(invoice, "FA")).toBe("FA-2026-0008");
});

test("a product code has no separator between its prefix and its number", () => {
  const product: NumberLine = { ...invoice, kind: "product", prefix: "ART", next_number: "ART0061", yearly: false };

  expect(nextWithPrefix(product, "PRD")).toBe("PRD0061");
});
