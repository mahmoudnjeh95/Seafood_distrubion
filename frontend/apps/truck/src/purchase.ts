import type { PaymentTermsEnum } from "@frutti/api";
import { parseDecimalInput } from "@frutti/i18n";

// Sums of a purchase at the port as the driver types it (D-158), in millimes so nothing is lost to floats. The
// server computes the same figures again: these only show the driver what they are about to send.

/** "6.5" → 6500n: a decimal string with up to three decimals, in thousandths. */
function millimes(value: string): bigint {
  const negative = value.startsWith("-");
  const [whole = "0", fraction = ""] = (negative ? value.slice(1) : value).split(".");
  const thousandths = BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, "0").slice(0, 3));
  return negative ? -thousandths : thousandths;
}

function fromMillimes(value: bigint): string {
  const negative = value < 0n;
  const digits = (negative ? -value : value).toString().padStart(4, "0");
  return `${negative ? "-" : ""}${digits.slice(0, -3)}.${digits.slice(-3)}`;
}

/** What is left to pay: total minus paid, never below zero ("130.000", "100" → "30.000"). */
export function amountLeft(total: string, paid: string): string {
  const rest = millimes(total) - millimes(paid);
  return fromMillimes(rest > 0n ? rest : 0n);
}

/** kg × price per kg, rounded half up to the millime; null until both are readable and the weight is above zero. */
export function lineAmount(kilos: string, price: string): string | null {
  const weight = parseDecimalInput(kilos.trim(), 3);
  const cost = parseDecimalInput(price.trim(), 3);
  if (weight === null || cost === null || weight.startsWith("-") || cost.startsWith("-")) return null;
  if (millimes(weight) === 0n) return null;
  // grams × millimes per kg = millionths of a millime; round half up to the millime.
  const product = millimes(weight) * millimes(cost);
  return fromMillimes((product + 500n) / 1000n);
}

/** What the purchase owes, what is given (the typed sums), and what is left to pay (never below zero). */
export function purchaseTotals(
  lines: { kilos: string; price: string }[],
  given: string[],
): { total: string; paid: string; rest: string; overpaid: boolean } {
  const total = lines.reduce((sum, line) => {
    const amount = lineAmount(line.kilos, line.price);
    return amount === null ? sum : sum + millimes(amount);
  }, 0n);
  const paid = given.reduce((sum, typed) => {
    const amount = parseDecimalInput(typed.trim(), 3);
    return amount === null || amount.startsWith("-") ? sum : sum + millimes(amount);
  }, 0n);
  const rest = total > paid ? total - paid : 0n;
  // More given than the purchase is worth: a typing mistake the server refuses, so it is never sent.
  return { total: fromMillimes(total), paid: fromMillimes(paid), rest: fromMillimes(rest), overpaid: paid > total };
}

/** When the purchase is due by its deal, as the server computes it: the day itself, N days later, or the end of
 * the month + N days. Calendar dates only. */
export function dueDateOn(boughtOn: string, terms: PaymentTermsEnum, days: number): string {
  const [year, month, day] = boughtOn.split("-").map(Number);
  if (!year || !month || !day) return boughtOn;
  const at = (y: number, m: number, d: number) => new Date(Date.UTC(y, m, d)).toISOString().slice(0, 10);
  if (terms === "days") return at(year, month - 1, day + days);
  // Day 0 of the next month is the last day of this one.
  if (terms === "month_end") return at(year, month, days);
  return boughtOn;
}
