import { describe, expect, it } from "vitest";

import { TAB_QUERY, waitingLate } from "./portfolio";

describe("portfolio tabs", () => {
  it("lists received effets to hand to the bank and ours to be debited", () => {
    expect(TAB_QUERY.toRemit).toEqual({ direction: "received", status: "portfolio" });
    expect(TAB_QUERY.issued).toEqual({ direction: "issued", status: "issued" });
  });

  it("marks late only what still waits for the bank", () => {
    expect(waitingLate({ status: "portfolio", due_on: "2026-10-01" }, "2026-10-31")).toBe(true);
    expect(waitingLate({ status: "cashed", due_on: "2026-10-01" }, "2026-10-31")).toBe(false);
    expect(waitingLate({ status: "issued", due_on: "2026-10-31" }, "2026-10-31")).toBe(false);
  });
});
