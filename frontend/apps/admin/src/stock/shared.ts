import type { StockMovementKindEnum } from "@frutti/api";

export const MOVEMENT_KINDS: StockMovementKindEnum[] = [
  "receipt",
  "transfer",
  "sale",
  "customer_return",
  "supplier_return",
  "loss",
  "adjustment",
  "count_correction",
];

/** The prototype's colours: receipts green, transfers blue, sales coral, losses red. */
export const MOVEMENT_TONES = {
  receipt: "good",
  transfer: "sea",
  sale: "coral",
  customer_return: "neutral",
  supplier_return: "neutral",
  loss: "bad",
  adjustment: "warn",
  count_correction: "warn",
} as const satisfies Record<StockMovementKindEnum, string>;

const STORAGE_KEY = "frutti.stock.view";
export type StockView = "cards" | "list";

/** The view the user last chose on this browser; cards when nothing is saved or storage is blocked. */
export function savedStockView(): StockView {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "list" ? "list" : "cards";
  } catch {
    return "cards";
  }
}

export function saveStockView(view: StockView): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, view);
  } catch {
    // Private window or blocked storage: the choice simply is not remembered.
  }
}
