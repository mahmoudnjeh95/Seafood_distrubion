import { describe, expect, it } from "vitest";

import { filterParams, isFiltered, NO_FILTERS, statusTone } from "./listFilters";

describe("règlements list filters", () => {
  it("sends only the filters chosen", () => {
    expect(filterParams(NO_FILTERS)).toEqual({});
    expect(isFiltered(NO_FILTERS)).toBe(false);
    const chosen = { dateFrom: "2026-10-01", dateTo: "", method: "bill", state: "voided" } as const;
    expect(filterParams(chosen)).toEqual({ date_from: "2026-10-01", method: "bill", state: "voided" });
    expect(isFiltered(chosen)).toBe(true);
  });

  it("colours an effet by where it stands", () => {
    expect(statusTone("portfolio")).toBe("neutral");
    expect(statusTone("deposited")).toBe("sea");
    expect(statusTone("debited")).toBe("good");
    expect(statusTone("unpaid")).toBe("bad");
    expect(statusTone("cancelled")).toBe("warn");
  });
});
