import { canAccess, type Session } from "@frutti/auth";
import type { QueryClient } from "@tanstack/react-query";

/** Locations and trucks are read together on the stock screen: both are refreshed after any change. */
export function refreshLocations(queryClient: QueryClient) {
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" &&
      (query.queryKey[0].startsWith("/api/v1/locations") || query.queryKey[0].startsWith("/api/v1/trucks")),
  });
}

/** The server refuses changes from other roles; this only avoids showing buttons that would fail. */
export function canEditLocations(session: Session): boolean {
  return canAccess(session, "stock", "write");
}
