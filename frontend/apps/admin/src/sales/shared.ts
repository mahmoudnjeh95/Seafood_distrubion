import type { DeliveryStatusEnum, SaleStatusEnum } from "@frutti/api";
import type { Session } from "@frutti/auth";
import type { QueryClient } from "@tanstack/react-query";

/** After a sale changes, refresh sales, quotes (their sale link), stock and lots: a sale moves all of them. */
export function refreshAfterSale(queryClient: QueryClient) {
  const prefixes = [
    "/api/v1/sales",
    "/api/v1/quotes",
    "/api/v1/batches",
    "/api/v1/locations",
    "/api/v1/stock",
    "/api/v1/price-board",
  ];
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && prefixes.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
  });
}

/** The server refuses sales from the accountant; this only avoids showing buttons that would fail. */
export function canSell(session: Session): boolean {
  return session.role === "owner" || session.role === "manager";
}

export const SALE_STATUSES: SaleStatusEnum[] = ["draft", "confirmed", "cancelled"];

export const STATUS_TONES = {
  draft: "neutral",
  confirmed: "good",
  cancelled: "bad",
} as const satisfies Record<SaleStatusEnum, string>;

/** Where the BL of a truck load stands (D-178). */
export const DELIVERY_TONES = {
  to_deliver: "warn",
  delivered: "good",
  partial: "sea",
  cancelled: "bad",
} as const satisfies Record<DeliveryStatusEnum, string>;

/** "2026-10-11T10:30" typed in a date-time input (local time) → the moment the API expects, or null. */
export function momentOf(localValue: string): string | null {
  if (!localValue) return null;
  const moment = new Date(localValue);
  return Number.isNaN(moment.getTime()) ? null : moment.toISOString();
}

/** A moment from the API shown in a date-time input, in the browser's local time ("2026-10-11T10:30"). */
export function localInputOf(iso: string): string {
  const moment = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return (
    `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}` +
    `T${pad(moment.getHours())}:${pad(moment.getMinutes())}`
  );
}
