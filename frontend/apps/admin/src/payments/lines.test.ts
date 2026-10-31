import { describe, expect, it } from "vitest";

import {
  addMonths,
  errorsByLine,
  lineProblems,
  linesPayload,
  linesTotal,
  newLine,
  nextNumber,
  splitIntoEffets,
} from "./lines";

describe("payment lines", () => {
  it("adds up the readable amounts", () => {
    const lines = [newLine("cash", "500"), newLine("cheque", "1 000,5"), newLine("bill", "abc")];
    expect(linesTotal(lines)).toBe("1500.500");
  });

  it("names what each line still misses", () => {
    const cheque = { ...newLine("cheque", "10"), number: "", bank: "" };
    const bill = { ...newLine("bill", "10"), number: "T1", bank: "3" };
    expect(lineProblems([newLine("", "0"), newLine("cash", "-1"), cheque, bill, newLine("transfer", "")])).toEqual({
      0: { method: "required", amount: "positive" },
      1: { amount: "money" },
      2: { number: "required", bank: "required" },
      3: { due_on: "required" },
      4: { amount: "required" },
    });
    expect(lineProblems([newLine("cash", "12,5")])).toEqual({});
  });

  it("sends a cheque with its paper fields and cash with its reference", () => {
    const cheque = { ...newLine("cheque", "200"), number: " 4401 ", bank: "7", dueOn: "2026-12-01", drawer: "X" };
    const transfer = { ...newLine("transfer", "50,25"), reference: "VIR-1" };
    expect(linesPayload([cheque, transfer], { withDrawer: true })).toEqual([
      { method: "cheque", amount: "200", number: "4401", bank: 7, due_on: "2026-12-01", drawer: "X" },
      { method: "transfer", amount: "50.25", reference: "VIR-1" },
    ]);
    expect(linesPayload([cheque])[0]).not.toHaveProperty("drawer");
  });

  it("puts the server's line errors under their line", () => {
    expect(errorsByLine({ "lines.2.number": "Déjà enregistré", amount: "Total faux" })).toEqual({
      lines: { 2: { number: "Déjà enregistré" } },
      rest: { amount: "Total faux" },
    });
  });
});

describe("Répartir", () => {
  it("keeps the day of the month, or its last day", () => {
    expect(addMonths("2026-01-31", 1)).toBe("2026-02-28");
    expect(addMonths("2026-11-15", 2)).toBe("2027-01-15");
    expect(addMonths("2028-01-31", 1)).toBe("2028-02-29");
  });

  it("counts paper numbers on, keeping their zeros", () => {
    expect(nextNumber("004401", 1)).toBe("004402");
    expect(nextNumber("TR-09", 2)).toBe("TR-11");
    expect(nextNumber("ABC", 1)).toBe("");
  });

  it("splits a total into equal effets a month apart, the odd millimes on the last", () => {
    expect(splitIntoEffets({ total: "1000.000", count: 3, firstDue: "2026-11-30", firstNumber: "0099" })).toEqual([
      { amount: "333.333", dueOn: "2026-11-30", number: "0099" },
      { amount: "333.333", dueOn: "2026-12-30", number: "0100" },
      { amount: "333.334", dueOn: "2027-01-30", number: "0101" },
    ]);
    expect(splitIntoEffets({ total: "0", count: 3, firstDue: "" })).toEqual([]);
  });
});
