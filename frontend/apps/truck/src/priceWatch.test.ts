import type { MyStockLine } from "@frutti/api";
import { describe, expect, test } from "vitest";

import { priceChanges } from "./priceWatch";

function line(productId: number, unitPrice: string | null): MyStockLine {
  return {
    product_id: productId,
    product_name: `Produit ${productId}`,
    product_name_ar: "",
    quantity: "10.000",
    unit_price: unitPrice,
    photo_url: null,
  };
}

describe("priceChanges (P3-T02)", () => {
  test("a product whose price moved is a change, with the old and the new price", () => {
    expect(priceChanges({ "1": "45.000" }, [line(1, "48.000")])).toEqual([
      { productId: 1, productName: "Produit 1", from: "45.000", to: "48.000" },
    ]);
  });

  test("the same price written with other decimals is not a change", () => {
    expect(priceChanges({ "1": "45.000" }, [line(1, "45")])).toEqual([]);
  });

  test("a product the phone never saw is not a change: its first price is only remembered", () => {
    expect(priceChanges({ "1": "45.000" }, [line(2, "20.000")])).toEqual([]);
  });

  test("a price that appears or disappears is a change too", () => {
    expect(priceChanges({ "1": null, "2": "30.000" }, [line(1, "50.000"), line(2, null)])).toEqual([
      { productId: 1, productName: "Produit 1", from: null, to: "50.000" },
      { productId: 2, productName: "Produit 2", from: "30.000", to: null },
    ]);
  });
});
