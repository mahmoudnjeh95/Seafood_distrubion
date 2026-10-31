// The means of one règlement (D-197, D-208): some cash, cheques, traites, a transfer... typed line by line and
// previewed in the browser with exact thousandths (see lib/decimal.ts). The server checks the same rules again.
import { formatMoney, parseDecimalInput } from "@frutti/i18n";

import { fromThousandths, sum, toThousandths } from "../lib/decimal";

/** One line as typed. `number`, `bank`, `dueOn` and `drawer` are for a cheque or a traite only. */
export type PaymentLine<M extends string = string> = {
  key: number;
  method: M | "";
  amount: string;
  reference: string;
  number: string;
  bank: string;
  dueOn: string;
  drawer: string;
};

export type LineField = "method" | "amount" | "number" | "bank" | "due_on";
export type LineProblem = "required" | "money" | "positive";

let lastKey = 0;

/** A new empty line (or one with its method and amount). */
export function newLine<M extends string>(method: M | "" = "", amount = ""): PaymentLine<M> {
  lastKey += 1;
  return { key: lastKey, method, amount, reference: "", number: "", bank: "", dueOn: "", drawer: "" };
}

/** A cheque or a traite: an effet with a number, a bank and an échéance, followed by the treasury. */
export const isPaper = (method: string) => method === "cheque" || method === "bill";

/** The line's amount as an API decimal, or null when it is not a readable positive amount. */
export function lineAmount(line: PaymentLine): string | null {
  const value = parseDecimalInput(line.amount.trim(), 3);
  if (value === null || value.startsWith("-") || toThousandths(value) === 0n) return null;
  return value;
}

/** The sum of the lines that have a readable amount (others count for nothing until fixed). */
export function linesTotal(lines: readonly PaymentLine[]): string {
  return sum(lines.map(lineAmount).filter((value): value is string => value !== null));
}

/** What the browser can already say about each line, by line index and field; empty when all look fine. */
export function lineProblems(lines: readonly PaymentLine[]): Record<number, Partial<Record<LineField, LineProblem>>> {
  const problems: Record<number, Partial<Record<LineField, LineProblem>>> = {};
  lines.forEach((line, index) => {
    const found: Partial<Record<LineField, LineProblem>> = {};
    if (!line.method) found.method = "required";
    const typed = line.amount.trim();
    const value = parseDecimalInput(typed, 3);
    if (typed === "") found.amount = "required";
    else if (value === null || value.startsWith("-")) found.amount = "money";
    else if (toThousandths(value) === 0n) found.amount = "positive";
    if (isPaper(line.method)) {
      if (!line.number.trim()) found.number = "required";
      if (!line.bank) found.bank = "required";
      if (line.method === "bill" && !line.dueOn) found.due_on = "required";
    }
    if (Object.keys(found).length > 0) problems[index] = found;
  });
  return problems;
}

export type LinePayload<M extends string> = {
  method: M;
  amount: string;
  reference?: string;
  number?: string;
  bank?: number | null;
  due_on?: string | null;
  drawer?: string;
};

/** The lines to send. Call it once `lineProblems` is empty: every line then has a method and an amount. */
export function linesPayload<M extends string>(
  lines: readonly PaymentLine<M>[],
  { withDrawer = false }: { withDrawer?: boolean } = {},
): LinePayload<M>[] {
  return lines.map((line) => {
    const method = line.method as M;
    const amount = lineAmount(line) ?? "0";
    if (!isPaper(method)) return { method, amount, reference: line.reference.trim() };
    return {
      method,
      amount,
      number: line.number.trim(),
      bank: line.bank ? Number(line.bank) : null,
      due_on: line.dueOn || null,
      ...(withDrawer ? { drawer: line.drawer.trim() } : {}),
    };
  });
}

/** The server's errors on `lines.<index>.<field>`, by line index and field; `rest` keeps the others. */
export function errorsByLine(serverErrors: Record<string, string>): {
  lines: Record<number, Record<string, string>>;
  rest: Record<string, string>;
} {
  const lines: Record<number, Record<string, string>> = {};
  const rest: Record<string, string> = {};
  for (const [key, message] of Object.entries(serverErrors)) {
    const match = /^lines\.(\d+)\.(\w+)$/.exec(key);
    if (match) (lines[Number(match[1])] ??= {})[match[2] ?? ""] = message;
    else rest[key] = message;
  }
  return { lines, rest };
}

/** "2026-01-31" + 1 month = "2026-02-28": the same day of the month, or its last day when shorter. */
export function addMonths(day: string, months: number): string {
  const [year, month, date] = day.split("-").map(Number) as [number, number, number];
  const index = year * 12 + (month - 1) + months;
  const nextYear = Math.floor(index / 12);
  const nextMonth = (index % 12) + 1;
  const last = new Date(Date.UTC(nextYear, nextMonth, 0)).getUTCDate();
  const pad = (value: number, width = 2) => String(value).padStart(width, "0");
  return `${pad(nextYear, 4)}-${pad(nextMonth)}-${pad(Math.min(date, last))}`;
}

/** The next paper number: "004401" → "004402", "TR-09" → "TR-10"; a number with no digits at its end stays. */
export function nextNumber(number: string, step: number): string {
  const match = /^(.*?)(\d+)$/.exec(number.trim());
  if (!match) return step === 0 ? number.trim() : "";
  const [, prefix = "", digits = ""] = match;
  return `${prefix}${String(BigInt(digits) + BigInt(step)).padStart(digits.length, "0")}`;
}

export type Split = { amount: string; dueOn: string; number: string };

/** "Répartir": `total` in `count` equal effets, a month apart from `firstDue` (or `everyMonths`), numbered from
 * `firstNumber`. The millimes that do not divide go on the last one, so the effets add up to the total exactly. */
export function splitIntoEffets({
  total,
  count,
  firstDue,
  everyMonths = 1,
  firstNumber = "",
}: {
  total: string;
  count: number;
  firstDue: string;
  everyMonths?: number;
  firstNumber?: string;
}): Split[] {
  const whole = toThousandths(total);
  if (count < 1 || whole <= 0n) return [];
  const part = whole / BigInt(count);
  return Array.from({ length: count }, (_, index) => ({
    amount: fromThousandths(index === count - 1 ? whole - part * BigInt(count - 1) : part),
    dueOn: firstDue ? addMonths(firstDue, index * everyMonths) : "",
    number: firstNumber ? nextNumber(firstNumber, index) : "",
  }));
}

/** One means in a short line for the confirm window: "Chèque 4401 · BIAT · 30/11/2026 — 1 000,000 DT". */
export function describeLine<M extends string>(
  line: PaymentLine<M>,
  {
    methodLabel,
    banks,
    formatDate,
  }: {
    methodLabel: (method: M) => string;
    banks: readonly { id: number; code: string }[];
    formatDate: (day: string) => string;
  },
): string {
  const amount = parseDecimalInput(line.amount.trim(), 3) ?? "0";
  const parts = [line.method ? methodLabel(line.method) : ""];
  if (isPaper(line.method)) {
    parts.push(line.number.trim());
    const bank = banks.find((one) => String(one.id) === line.bank);
    if (bank) parts.push(`· ${bank.code}`);
    if (line.dueOn) parts.push(`· ${formatDate(line.dueOn)}`);
  } else if (line.reference.trim()) {
    parts.push(line.reference.trim());
  }
  return `${parts.filter(Boolean).join(" ")} — ${formatMoney(amount)}`;
}
