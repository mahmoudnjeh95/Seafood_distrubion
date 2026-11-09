import type { CountStatusEnum, LossReasonEnum, LossStatusEnum } from "@frutti/api";
import { canAccess, type Session } from "@frutti/auth";
import type { QueryClient } from "@tanstack/react-query";

/** After a loss or a count, refresh them and everything that shows stock. */
export function refreshAfterStockCheck(queryClient: QueryClient) {
  const prefixes = [
    "/api/v1/losses",
    "/api/v1/counts",
    "/api/v1/stock-settings",
    "/api/v1/locations",
    "/api/v1/transfers",
  ];
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && prefixes.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
  });
}

/** The server refuses other roles; this only avoids showing buttons that would fail. */
export function canRecordStockChecks(session: Session): boolean {
  return canAccess(session, "stock", "write");
}

/** Only the owner approves or refuses a waiting loss, and sets the threshold (checked by the server too). */
export function isOwner(session: Session): boolean {
  return canAccess(session, "stock", "full");
}

export const LOSS_REASONS: LossReasonEnum[] = ["spoiled", "damaged", "expired", "cold_chain", "other"];

export const LOSS_TONES = { pending: "warn", approved: "bad", rejected: "neutral" } as const satisfies Record<
  LossStatusEnum,
  string
>;

export const COUNT_TONES = { counting: "warn", approved: "good", cancelled: "neutral" } as const satisfies Record<
  CountStatusEnum,
  string
>;
