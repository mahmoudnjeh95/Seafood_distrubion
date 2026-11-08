import type { PriceRequestStatusEnum } from "@frutti/api";
import type { QueryClient } from "@tanstack/react-query";

/** The pill colour of each price request status (D-289). */
export const REQUEST_TONE: Record<PriceRequestStatusEnum, "neutral" | "sea" | "good"> = {
  open: "sea",
  ordered: "good",
  cancelled: "neutral",
};

/** After a request changes, refresh requests and purchase orders (ordering makes orders). */
export function refreshPriceRequests(queryClient: QueryClient) {
  const prefixes = ["/api/v1/price-requests", "/api/v1/purchase-orders"];
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && prefixes.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
  });
}

/** The API writes "20.250"; people here write "20,250". */
export const asTyped = (value: string) => value.replace(".", ",");
