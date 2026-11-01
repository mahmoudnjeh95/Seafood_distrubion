import type { PartyDocumentRow } from "@frutti/api";

export type PartyCounts = Pick<PartyDocumentRow, "deliveries" | "invoices" | "total">;

const NONE: PartyCounts = { deliveries: 0, invoices: 0, total: "0.000" };

/** A party's counts from the list: zeros when it has no document, nothing until the list has loaded. */
export function countsOf(rows: readonly PartyDocumentRow[] | undefined, partyId: number): PartyCounts | undefined {
  if (!rows) return undefined;
  return rows.find((row) => row.id === partyId) ?? NONE;
}
