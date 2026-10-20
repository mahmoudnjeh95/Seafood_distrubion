import type { PaymentMethodEnum } from "@frutti/api";

/** What the driver gave now (D-192): nothing, a part, or all. The method of the remainder is the office's choice. */
export type PaidMode = "none" | "part" | "all";
export type PayLine = { key: number; method: PaymentMethodEnum; amount: string; reference: string; cashOn: string };

/** The methods a driver can hand over at the port; a cheque or a traite also has a number and a cashing day. */
export const GIVEN_METHODS: Extract<PaymentMethodEnum, "cash" | "cheque" | "bill" | "transfer">[] = ["cash", "cheque", "bill", "transfer"];
export const hasPaper = (method: PaymentMethodEnum) => method === "cheque" || method === "bill";

let nextPayKey = 0;
export const blankPayLine = (method: PaymentMethodEnum = "cash", amount = ""): PayLine => {
  nextPayKey += 1;
  return { key: nextPayKey, method, amount, reference: "", cashOn: "" };
};

/** The lines that are really sent: none, the typed ones, or one line for the whole total. */
export function effectiveLines(mode: PaidMode, lines: PayLine[], total: string): PayLine[] {
  if (mode === "none") return [];
  if (mode === "all") return [{ ...(lines[0] ?? blankPayLine()), amount: total }];
  return lines;
}
