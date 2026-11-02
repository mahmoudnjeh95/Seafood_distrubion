import type { SetURLSearchParams } from "react-router";

// React Router does not queue two address changes made in the same event (the second starts from the old address
// and drops the first). A typed search that also goes back to page 1 does exactly that, so the changes of one tick
// are built on each other here.
let pending: URLSearchParams | null = null;

export function changeParams(
  current: URLSearchParams,
  setParams: SetURLSearchParams,
  changes: Record<string, string | null>,
): void {
  const next = new URLSearchParams(pending ?? current);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === "") next.delete(key);
    else next.set(key, value);
  }
  pending = next;
  queueMicrotask(() => {
    pending = null;
  });
  setParams(new URLSearchParams(next), { replace: true });
}
