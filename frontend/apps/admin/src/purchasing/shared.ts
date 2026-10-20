import type { SupplierInvoiceStatusEnum } from "@frutti/api";
import type { QueryClient } from "@tanstack/react-query";

/** After an invoice or a payment, refresh receipts, invoices, payments and balances: they all show it. */
export function refreshPurchasing(queryClient: QueryClient) {
  const prefixes = [
    "/api/v1/receipts",
    "/api/v1/supplier-invoices",
    "/api/v1/supplier-payments",
    "/api/v1/supplier-balances",
    "/api/v1/supplier-settlements",
  ];
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && prefixes.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
  });
}

/** The pill colour of each invoice status: grey draft, blue owed, amber partly paid, green paid. */
export const STATUS_TONE: Record<SupplierInvoiceStatusEnum, "neutral" | "sea" | "warn" | "good"> = {
  draft: "neutral",
  posted: "sea",
  partly_paid: "warn",
  paid: "good",
};

/** "2026-10-11" + 30 days → "2026-11-10", on calendar dates (no time zone involved). */
export function addDays(isoDate: string, days: number): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return isoDate;
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

/** Provisional default (D-043): a supplier invoice is due 30 days after its date until the client says otherwise. */
export const DEFAULT_PAYMENT_DAYS = 30;

/** A positive integer id from the URL (`?fournisseur=3`), or null. */
export function idFrom(value: string | null): number | null {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}
