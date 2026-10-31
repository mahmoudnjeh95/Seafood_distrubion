// The tabs of the portfolio (P9-T04a, D-216): which effets each one lists.
import type { InstrumentStatusEnum, ListInstrumentsParams } from "@frutti/api";

export const TABS = ["toRemit", "atBank", "cashed", "unpaid", "issued", "debited", "deposits"] as const;
export type PortfolioTab = (typeof TABS)[number];

/** The list query of each tab of effets (the bordereaux tab lists deposits instead). */
export const TAB_QUERY: Record<Exclude<PortfolioTab, "deposits">, ListInstrumentsParams> = {
  toRemit: { direction: "received", status: "portfolio" },
  atBank: { direction: "received", status: "deposited" },
  cashed: { direction: "received", status: "cashed" },
  unpaid: { direction: "received", status: "unpaid" },
  issued: { direction: "issued", status: "issued" },
  debited: { direction: "issued", status: "debited" },
};

const WAITING: readonly InstrumentStatusEnum[] = ["portfolio", "deposited", "issued"];

/** An effet still waiting for the bank whose échéance has passed (`today` as "2026-10-31"). */
export function waitingLate(effet: { status: InstrumentStatusEnum; due_on: string }, today: string): boolean {
  return WAITING.includes(effet.status) && effet.due_on < today;
}
