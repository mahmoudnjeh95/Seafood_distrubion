import type { NumberLine } from "@frutti/api";
import { expect, test } from "vitest";

import { DRAFT_WORD, nextWithPrefix } from "./numbering";

const invoice: NumberLine = {
  kind: "invoice",
  title: "Facture",
  group: "Ventes",
  prefix: "FA",
  default_prefix: "FA",
  yearly: true,
  next_number: "FA-2026-0008",
  has_draft: true,
  draft_prefix: "",
  next_draft_number: "BROUILLON-2026-0012",
};

test("the preview reads with the prefix typed, the year and the number kept", () => {
  expect(nextWithPrefix(invoice, "FACT")).toBe("FACT-2026-0008");
  expect(nextWithPrefix(invoice, "FA")).toBe("FA-2026-0008");
});

test("a product code has no separator between its prefix and its number", () => {
  const product: NumberLine = { ...invoice, kind: "product", prefix: "ART", next_number: "ART0061", yearly: false };

  expect(nextWithPrefix(product, "PRD")).toBe("PRD0061");
});

test("a draft reference has its own counter: BFA-2026-0012 while the next invoice is FA-2026-0008", () => {
  expect(nextWithPrefix(invoice, "BFA", true)).toBe("BFA-2026-0012");
  expect(nextWithPrefix(invoice, DRAFT_WORD, true)).toBe("BROUILLON-2026-0012");
  const saved = { ...invoice, draft_prefix: "BFA", next_draft_number: "BFA-2026-0012" };
  expect(nextWithPrefix(saved, "BF", true)).toBe("BF-2026-0012");
});
