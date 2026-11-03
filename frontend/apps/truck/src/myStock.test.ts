import type { MyStockLine } from "@frutti/api";
import { expect, test } from "vitest";

import { truckIsEmpty } from "./myStock";

const line = (product_id: number, quantity: string): MyStockLine => ({
  product_id,
  product_name: `P${product_id}`,
  product_name_ar: "",
  quantity,
  unit_price: "10.000",
  photo_url: null,
});

test("a truck with no stock line is empty", () => {
  expect(truckIsEmpty([], {})).toBe(true);
});

test("a truck with kilos left is not empty", () => {
  expect(truckIsEmpty([line(1, "0.000"), line(2, "3.500")], {})).toBe(false);
});

test("kilos promised to sales waiting to be sent do not count", () => {
  expect(truckIsEmpty([line(1, "3.500")], { 1: 3.5 })).toBe(true);
  expect(truckIsEmpty([line(1, "3.500")], { 1: 2 })).toBe(false);
});
