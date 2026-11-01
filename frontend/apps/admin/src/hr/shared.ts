import type { SalaryPaymentKindEnum, SalaryPaymentMethodEnum, SalaryStatusEnum } from "@frutti/api";
import type { Session } from "@frutti/auth";
import type { QueryClient } from "@tanstack/react-query";

import { todayInTunis } from "../receipts/shared";

/** The server refuses everything else (403); this only avoids showing screens and buttons that would fail. */
export function canReadPay(session: Session): boolean {
  return session.role === "owner" || session.role === "accountant";
}

/** Only the owner changes salaries and employees (D-055). */
export function canWritePay(session: Session): boolean {
  return session.role === "owner";
}

/** After a change, employees, salaries, payments, totals and days on a lot are all refreshed: they show each other. */
export function refreshHr(queryClient: QueryClient) {
  const prefixes = [
    "/api/v1/employees",
    "/api/v1/salary-records",
    "/api/v1/salary-payments",
    "/api/v1/payroll-summary",
    "/api/v1/lot-work-days",
  ];
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && prefixes.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
  });
}

export const PAYMENT_METHODS: readonly SalaryPaymentMethodEnum[] = ["cash", "cheque", "transfer", "other"];
export const PAYMENT_KINDS: readonly SalaryPaymentKindEnum[] = ["salary", "advance"];

/** The pill colour of each salary status. */
export const STATUS_TONE: Record<SalaryStatusEnum, "neutral" | "good"> = {
  draft: "neutral",
  approved: "good",
};

/** The first day of this month in Tunisian time, "2026-10-01". */
export function currentMonth(): string {
  return `${todayInTunis().slice(0, 7)}-01`;
}

/** "2026-10-01" + 1 → "2026-11-01", on calendar months. */
export function shiftMonth(month: string, delta: number): string {
  const [year, number] = month.split("-").map(Number);
  if (!year || !number) return month;
  const shifted = new Date(Date.UTC(year, number - 1 + delta, 1));
  return shifted.toISOString().slice(0, 10);
}

/** "2026-10-01" → "octobre 2026". */
export function monthLabel(month: string, language: string): string {
  return new Intl.DateTimeFormat(language === "ar" ? "ar-TN" : "fr-TN", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${month}T00:00:00Z`));
}

/** Fractions of a day offered when recording days on a lot. */
export const DAY_FRACTIONS = [
  { value: "0.25", label: "quarter" },
  { value: "0.5", label: "half" },
  { value: "0.75", label: "threeQuarters" },
  { value: "1", label: "full" },
] as const;
