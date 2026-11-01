import type { PartyDocumentRow } from "@frutti/api";
import { formatMoney, useTranslation } from "@frutti/i18n";

export type PartyCounts = Pick<PartyDocumentRow, "deliveries" | "invoices" | "total">;

const NONE: PartyCounts = { deliveries: 0, invoices: 0, total: "0.000" };

/** A party's counts from the list: zeros when it has no document, nothing until the list has loaded. */
export function countsOf(rows: readonly PartyDocumentRow[] | undefined, partyId: number): PartyCounts | undefined {
  if (!rows) return undefined;
  return rows.find((row) => row.id === partyId) ?? NONE;
}

/** Beside a customer or supplier in a règlement's list: its BL (or BR), invoices and total (D-211). */
export function PartyDocumentCounts({
  counts,
  side,
}: {
  counts: PartyCounts | undefined;
  side: "customer" | "supplier";
}) {
  const { t } = useTranslation();
  if (!counts) return null;
  const deliveries =
    side === "customer"
      ? t("admin.treasury.documents.bl", { count: counts.deliveries })
      : t("admin.treasury.documents.br", { count: counts.deliveries });
  return (
    <span className="ml-auto shrink-0 text-xs whitespace-nowrap text-ink-2 tabular-nums">
      {[deliveries, t("admin.treasury.documents.invoices", { count: counts.invoices }), formatMoney(counts.total)].join(
        " · ",
      )}
    </span>
  );
}
