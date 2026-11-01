// How the driver paid a road expense (D-205), and whether "La caisse" can pay it (D-220).

export const PAID_WITH = ["cash", "pocket", "card"] as const;
export type PaidWith = (typeof PAID_WITH)[number];

/**
 * "La caisse" is off when the day started with 0 DT, or has not started: the box has nothing to pay from. The server
 * refuses it the same way (expenses.services). `openingCash` is the day's starting cash, `undefined` with no day.
 */
export function cashOffOn(openingCash: string | undefined): boolean {
  return openingCash === undefined || Number(openingCash) === 0;
}

/** The method used: "La caisse" falls back to "Ma poche" while it is off. */
export function paidWithOn(choice: PaidWith, cashOff: boolean): PaidWith {
  return cashOff && choice === "cash" ? "pocket" : choice;
}
