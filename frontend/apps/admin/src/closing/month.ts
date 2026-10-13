/** "2026-10-01" → "2026-10", the address of a month in the API. */
export const monthKey = (day: string) => day.slice(0, 7);

/** The month as people say it: "octobre 2026". */
export function monthLabel(day: string): string {
  const [year, month] = day.split("-");
  return new Date(Number(year), Number(month) - 1, 1).toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
}

/** The month's first and last day, ISO, from its first day ("2026-10-01" → "2026-10-01" .. "2026-10-31"):
 * what the month closing's figures link to in the expenses list (D-122). */
export function monthRange(first: string): { from: string; to: string } {
  const [year, month] = first.split("-");
  const last = new Date(Number(year), Number(month), 0).getDate();
  return { from: first, to: `${first.slice(0, 8)}${String(last).padStart(2, "0")}` };
}
