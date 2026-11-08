import type { Alert } from "@frutti/api";
import type { QueryClient } from "@tanstack/react-query";

/** km with a thin thousands space: "120 500 km". */
export function formatKm(km: number | null | undefined): string {
  return km == null ? "—" : `${new Intl.NumberFormat("fr-FR").format(km)} km`;
}

/** Only digits, at most `size` of them. */
export function digits(value: string, size = 7): string {
  return value.replace(/\D/g, "").slice(0, size);
}

/** Today's date in the browser, as the `YYYY-MM-DD` the date input and the API use. */
export function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

export const SELECT_CLASSES = "rounded-control border border-line bg-surface px-3 py-2 text-ink";

export const PAPER_TONES = { ok: "good", soon: "warn", expired: "bad", missing: "neutral" } as const;

export const STATE_TONES = { ok: "good", soon: "warn", late: "bad", unknown: "neutral" } as const;

/** Everything of the fleet module is read together: refresh it all after a change. */
export function refreshFleet(queryClient: QueryClient) {
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" &&
      /^\/api\/v1\/(fleet|maintenance|trucks\/\d+\/odometer|papers|expenses|my-day\/alerts)/.test(query.queryKey[0]),
  });
}

/** The worst state of each truck with something soon or late: the badge on its icon (P10-T05). */
export function truckStates(alerts: Alert[] | undefined): Map<number, "soon" | "late"> {
  const states = new Map<number, "soon" | "late">();
  for (const alert of alerts ?? []) {
    if (alert.truck_id === null) continue;
    if (alert.state === "late" || !states.has(alert.truck_id)) states.set(alert.truck_id, alert.state);
  }
  return states;
}
