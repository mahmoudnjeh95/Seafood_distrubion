import type { InstrumentStatusEnum } from "@frutti/api";

// The filters of the règlements lists (P9-T03b), shared by the list, its totals and its Excel file.

export type ListState = "active" | "voided" | "unallocated";

export type ListFilters<M extends string = string> = {
  dateFrom: string;
  dateTo: string;
  method: M | "";
  state: ListState | "";
};

/** The value of "all" in a filter's select (a Radix select item cannot be empty). */
export const NO_CHOICE = "all";

export const NO_FILTERS: ListFilters<never> = { dateFrom: "", dateTo: "", method: "", state: "" };

/** The filters as API query parameters: only those chosen. */
export function filterParams<M extends string>(
  filters: ListFilters<M>,
): { date_from?: string; date_to?: string; method?: M; state?: ListState } {
  return {
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
    ...(filters.method ? { method: filters.method } : {}),
    ...(filters.state ? { state: filters.state } : {}),
  };
}

/** True when at least one filter is chosen. */
export const isFiltered = (filters: ListFilters) =>
  filters.dateFrom !== "" || filters.dateTo !== "" || filters.method !== "" || filters.state !== "";

/** The tone of an effet's state: waiting (neutral), at the bank (sea), done (good), refused or unpaid (bad). */
export function statusTone(status: InstrumentStatusEnum): "neutral" | "sea" | "good" | "bad" | "warn" {
  switch (status) {
    case "deposited":
      return "sea";
    case "cashed":
    case "debited":
    case "endorsed":
      return "good";
    case "unpaid":
    case "rejected":
      return "bad";
    case "cancelled":
    case "returned":
      return "warn";
    default:
      return "neutral";
  }
}
