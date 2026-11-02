import { useSyncExternalStore } from "react";

// Display choices that belong to the person and the browser, not to the company: kept in localStorage, which can be
// blocked, so every read falls back to the default.
const TOTALS_KEY = "frutti.showTotals";
const listeners = new Set<() => void>();

export function getShowTotals(): boolean {
  try {
    return window.localStorage.getItem(TOTALS_KEY) !== "0";
  } catch {
    return true;
  }
}

export function setShowTotals(show: boolean): void {
  try {
    window.localStorage.setItem(TOTALS_KEY, show ? "1" : "0");
  } catch {
    // Not remembered after a reload; the change still applies now.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Whether lists show their "Total de la page" row (on by default; changed in the display settings). */
export function useShowTotals(): boolean {
  return useSyncExternalStore(subscribe, getShowTotals, () => true);
}
