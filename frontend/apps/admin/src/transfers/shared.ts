import type { TransferKindEnum, TransferStatusEnum } from "@frutti/api";
import { canAccess, type Session } from "@frutti/auth";
import type { QueryClient } from "@tanstack/react-query";

/** After a transfer changes, refresh transfers, truck days and stock: a validation moved kilos. */
export function refreshAfterTransfer(queryClient: QueryClient) {
  const prefixes = ["/api/v1/transfers", "/api/v1/locations", "/api/v1/batches"];
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && prefixes.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
  });
}

/** The server refuses transfers from other roles; this only avoids showing buttons that would fail. */
export function canRecordTransfers(session: Session): boolean {
  return canAccess(session, "transfers", "write");
}

export const KIND_ICONS = { load: "truck", return: "return", internal: "snow" } as const satisfies Record<
  TransferKindEnum,
  string
>;

export const STATUS_TONES = { draft: "warn", validated: "good", cancelled: "neutral" } as const satisfies Record<
  TransferStatusEnum,
  string
>;

/** Whether a decimal string is zero ("0.000", "-0.000"). */
export const isZero = (value: string) => /^-?0+(\.0+)?$/.test(value);
