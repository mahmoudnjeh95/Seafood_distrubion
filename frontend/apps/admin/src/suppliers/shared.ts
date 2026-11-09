import { canAccess, type Session } from "@frutti/auth";
import type { QueryClient } from "@tanstack/react-query";

/** Every cached answer about suppliers (list and detail) is refreshed after a change. */
export function refreshSuppliers(queryClient: QueryClient) {
  return queryClient.invalidateQueries({
    predicate: (query) => typeof query.queryKey[0] === "string" && query.queryKey[0].startsWith("/api/v1/suppliers"),
  });
}

/** The server refuses changes from other roles; this only avoids showing buttons that would fail. */
export function canEditSuppliers(session: Session): boolean {
  return canAccess(session, "suppliers", "write");
}
