import { describe, expect, it } from "vitest";

import { canCollect, isInstrumentMethod, lineErrors, todayInput } from "./shared";

describe("payments helpers", () => {
  it("formats today as a date input value", () => {
    expect(todayInput()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("lets the owner and the manager collect, not the accountant or a driver", () => {
    // The levels the server sends for each built-in role (D-306).
    const treasury: Record<string, string> = { manager: "write", accountant: "read", driver: "none" };
    const session = (role: string) =>
      ({ role, access: { treasury: treasury[role] ?? "none" } }) as Parameters<typeof canCollect>[0];
    expect(canCollect(session("owner"))).toBe(true);
    expect(canCollect(session("manager"))).toBe(true);
    expect(canCollect(session("accountant"))).toBe(false);
    expect(canCollect(session("driver"))).toBe(false);
  });

  it("asks a number, a bank and a due day for a cheque or a traite only", () => {
    expect(isInstrumentMethod("cheque")).toBe(true);
    expect(isInstrumentMethod("bill")).toBe(true);
    expect(isInstrumentMethod("cash")).toBe(false);
    expect(isInstrumentMethod("transfer")).toBe(false);
  });

  it("puts the errors of a payment line under its own fields", () => {
    expect(lineErrors({ "lines.0.bank": "Choisissez la banque.", customer: "Client inconnu." }, 0)).toEqual({
      bank: "Choisissez la banque.",
      customer: "Client inconnu.",
    });
  });
});
