import { describe, expect, it } from "vitest";

import { overCashLimit } from "./cashLimit";

describe("overCashLimit", () => {
  it("asks at the limit and above, not below", () => {
    expect(overCashLimit("5000.000", "5000.000")).toBe(true);
    expect(overCashLimit("6200.500", "5000.000")).toBe(true);
    expect(overCashLimit("4999.999", "5000.000")).toBe(false);
  });

  it("asks nothing while no amount is typed", () => {
    expect(overCashLimit(null, "5000.000")).toBe(false);
  });
});
