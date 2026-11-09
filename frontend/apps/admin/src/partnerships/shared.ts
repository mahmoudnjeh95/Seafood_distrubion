import type { PartnershipStatusEnum } from "@frutti/api";
import { canAccess, type Session } from "@frutti/auth";
import type { QueryClient } from "@tanstack/react-query";

/** Lot results and partnerships are the owner's business (D-060, D-061): the accountant reads them too.
 * The server refuses everyone else (403); this only avoids showing screens that would fail. */
export function canReadResults(session: Session): boolean {
  return canAccess(session, "closing", "read") || canAccess(session, "partnerships", "read");
}

/** Only the owner sets partnerships and closes or reopens a lot. */
export function canWriteResults(session: Session): boolean {
  return canAccess(session, "closing", "full") || canAccess(session, "partnerships", "full");
}

/** A rate as typed by people: "40.00" → "40", "25.50" → "25,5". */
export function formatRate(rate: string): string {
  const [whole, decimals = ""] = rate.split(".");
  const kept = decimals.replace(/0+$/, "");
  return kept ? `${whole},${kept}` : (whole ?? rate);
}

/** "1500.000" → "1500,000": an amount put back in an input as the person would type it. */
export const typed = (decimal: string) => decimal.replace(".", ",");

export const STATUS_TONE: Record<PartnershipStatusEnum, "neutral" | "good" | "warn" | "bad"> = {
  open: "warn",
  closed: "good",
  settled: "neutral",
  cancelled: "bad",
};

/** After a change, partnerships, lot results, the lot's stock and costs all show each other: refresh them. */
export function refreshLotResult(queryClient: QueryClient) {
  const prefixes = ["/api/v1/partnerships", "/api/v1/lots/", "/api/v1/batches", "/api/v1/lot-costs"];
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && prefixes.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
  });
}
