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

export const STATE_TONES = { ok: "good", soon: "warn", late: "bad", unknown: "neutral" } as const;

/** Everything of the fleet module is read together: refresh it all after a change. */
export function refreshFleet(queryClient: QueryClient) {
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" &&
      /^\/api\/v1\/(fleet|maintenance|trucks\/\d+\/odometer|papers|expenses)/.test(query.queryKey[0]),
  });
}
