import { describe, expect, it } from "vitest";

import { hitPath } from "./hitPath";

describe("hitPath", () => {
  it("opens each kind of hit on its own page", () => {
    expect(hitPath({ kind: "customer", id: 3 })).toBe("/clients/3");
    expect(hitPath({ kind: "supplier", id: 4 })).toBe("/fournisseurs/4");
    expect(hitPath({ kind: "product", id: 5 })).toBe("/stock/produits/5");
    expect(hitPath({ kind: "lot", id: 6 })).toBe("/stock/lots/6");
    expect(hitPath({ kind: "sale", id: 7 })).toBe("/ventes/7");
    expect(hitPath({ kind: "invoice", id: 8 })).toBe("/factures/8");
  });
});
