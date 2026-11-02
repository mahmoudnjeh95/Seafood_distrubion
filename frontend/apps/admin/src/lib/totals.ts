import { formatMoney } from "@frutti/i18n";

import { sum } from "./decimal";

/** The "Total de la page" figure of one money column, exact to the millime. An empty or odd value is left out; a
 * column that cannot be added shows a dash instead of breaking the page. */
export function totalOf<Row>(rows: readonly Row[], pick: (row: Row) => string | null | undefined): string {
  try {
    return formatMoney(sum(rows.map(pick).filter((value): value is string => !!value)));
  } catch {
    return "—";
  }
}
