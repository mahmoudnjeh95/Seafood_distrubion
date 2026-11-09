import type { InvoiceStatusEnum } from "@frutti/api";
import { canAccess, type Session } from "@frutti/auth";
import type { QueryClient } from "@tanstack/react-query";

/** After an invoice or a credit note changes, refresh invoices, credit notes and sales (their invoice link). */
export function refreshAfterInvoice(queryClient: QueryClient) {
  const prefixes = ["/api/v1/invoices", "/api/v1/credit-notes", "/api/v1/sales"];
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && prefixes.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
  });
}

/** The server refuses invoices from the accountant; this only avoids showing buttons that would fail. */
export function canInvoice(session: Session): boolean {
  return canAccess(session, "invoices", "write");
}

export const INVOICE_STATUSES: InvoiceStatusEnum[] = ["draft", "issued", "cancelled"];

export const STATUS_TONES = {
  draft: "neutral",
  issued: "good",
  cancelled: "bad",
} as const satisfies Record<InvoiceStatusEnum, string>;

export const isZero = (value: string | null | undefined) => !value || /^0+(\.0+)?$/.test(value);

/** An API decimal as people type it here: "19.00" becomes "19,00". */
export const toInput = (value: string | null | undefined) => (value ?? "").replace(".", ",");

/** A rate as "19" or "7,5" for a label or a placeholder. */
export function plainRate(value: string): string {
  const [whole = "0", decimals = ""] = value.split(".");
  const trimmed = decimals.replace(/0+$/, "");
  return trimmed ? `${whole},${trimmed}` : whole;
}
