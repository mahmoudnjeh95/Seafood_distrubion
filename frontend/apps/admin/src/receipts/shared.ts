import { canAccess, type Session } from "@frutti/auth";
import type { QueryClient } from "@tanstack/react-query";

/** After a receipt, refresh receipts, batches, last costs and stock: the receipt changed all of them. */
export function refreshAfterReceipt(queryClient: QueryClient) {
  const prefixes = ["/api/v1/receipts", "/api/v1/purchase-orders", "/api/v1/batches", "/api/v1/locations"];
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && prefixes.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
  });
}

/** The server refuses receipts from other roles; this only avoids showing buttons that would fail. */
export function canRecordReceipts(session: Session): boolean {
  return canAccess(session, "purchases", "write");
}

/** Today in Tunisia, as the API writes dates ("2026-10-11"). */
export function todayInTunis(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Tunis" }).format(new Date());
}
