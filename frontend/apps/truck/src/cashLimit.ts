import { useGetMyCashLimit } from "@frutti/api";

const KEY = "frutti.cashLimit";
/** The limit in force when nothing is known yet (the finance settings default, D-273). */
const DEFAULT_LIMIT = "5000.000";

function remembered(): string {
  try {
    return localStorage.getItem(KEY) ?? DEFAULT_LIMIT;
  } catch {
    return DEFAULT_LIMIT;
  }
}

/**
 * The cash limit the phone asks the driver to confirm at (D-280): the server's answer, kept on the phone so the
 * question is still asked with no connection. The server stays the judge; this only decides whether to ask.
 */
export function useCashLimit(): string {
  const query = useGetMyCashLimit();
  const fresh = query.data?.cash_limit;
  if (fresh === undefined) return remembered();
  try {
    localStorage.setItem(KEY, fresh);
  } catch {
    // Storage blocked: the answer still counts for this screen.
  }
  return fresh;
}

/** True when a cash amount is at or above the limit. */
export function overCashLimit(amount: string | null, limit: string): boolean {
  return amount !== null && Number(amount) >= Number(limit);
}
