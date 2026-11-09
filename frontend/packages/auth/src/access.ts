import type { LevelsEnum, Session } from "@frutti/api";

/** A person's level in one section of the admin app (D-306): none < read < write < full. */
export type Level = LevelsEnum;

/** The sections of the access matrix; the server's list is `apps.core.access.SECTIONS`. */
export type Section =
  | "dashboard"
  | "reports"
  | "quotes"
  | "sales"
  | "invoices"
  | "customers"
  | "prices"
  | "stock"
  | "transfers"
  | "fleet"
  | "day_closings"
  | "products"
  | "purchases"
  | "suppliers"
  | "documents"
  | "expenses"
  | "payroll"
  | "partnerships"
  | "closing"
  | "treasury"
  | "website"
  | "settings";

export const LEVELS: readonly Level[] = ["none", "read", "write", "full"];
const RANK: Record<Level, number> = { none: 0, read: 1, write: 2, full: 3 };

/** The person's level in a section, as the server sent it with the session. */
export function levelOf(session: Pick<Session, "access" | "role">, section: Section): Level {
  if (session.role === "owner") return "full";
  return session.access[section] ?? "none";
}

/**
 * Whether the person has at least `level` in `section`. The server checks the same thing on every call: this only
 * hides what would fail. "write" is what a manager does, "full" also what only the owner does.
 */
export function canAccess(session: Pick<Session, "access" | "role">, section: Section, level: Level): boolean {
  return RANK[levelOf(session, section)] >= RANK[level];
}
