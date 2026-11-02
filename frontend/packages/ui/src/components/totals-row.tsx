import { useTranslation } from "@frutti/i18n";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { useShowTotals } from "../lib/display-prefs";
import { Td } from "./table";

export type TotalsCell = { value: ReactNode; phoneHidden?: boolean } | null;

/** The last row of a table: the sum of what is on this page. `span` is the number of columns before the first
 * total; `cells` follow, one per remaining column (`null` leaves it empty). Hidden when the user turned totals off. */
export function TotalsRow({ span, cells, label }: { span: number; cells: TotalsCell[]; label?: string }) {
  const { t } = useTranslation();
  const show = useShowTotals();
  if (!show) return null;
  return (
    <tfoot>
      <tr>
        <Td colSpan={span} className="bg-surface-2 text-end font-semibold">
          {label ?? t("common.table.pageTotal")}
        </Td>
        {cells.map((cell, index) => (
          <Td
            key={index}
            numeric
            className={cn("bg-surface-2 font-semibold whitespace-nowrap", cell?.phoneHidden && "max-[720px]:hidden")}
          >
            {cell?.value}
          </Td>
        ))}
      </tr>
    </tfoot>
  );
}
