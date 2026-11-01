import { fromThousandths, toThousandths } from "../lib/decimal";

/** What is still to pay on a balance (D-226): the positive part, "0.000" when the balance is a credit. The customer's
 * balance and the supplier's are read the same way, so the party card and the règlement form show one number. */
export function amountToPay(balance: string): string {
  return toThousandths(balance) > 0n ? balance : "0.000";
}

/** What we hold for the party when the balance is negative (a customer's credit, a supplier's advance), "0.000" otherwise. */
export function creditHeld(balance: string): string {
  const value = toThousandths(balance);
  return value < 0n ? fromThousandths(-value) : "0.000";
}
