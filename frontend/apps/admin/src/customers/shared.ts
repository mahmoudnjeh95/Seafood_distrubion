import { type CustomerType, useListCustomerTypes } from "@frutti/api";
import type { Session } from "@frutti/auth";
import type { QueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

/** Every cached answer about customers (list and detail) is refreshed after a change. */
export function refreshCustomers(queryClient: QueryClient) {
  return queryClient.invalidateQueries({
    predicate: (query) => typeof query.queryKey[0] === "string" && query.queryKey[0].startsWith("/api/v1/customers"),
  });
}

/** The server refuses changes from other roles; this only avoids showing buttons that would fail. */
export function canEditCustomers(session: Session): boolean {
  return session.role === "owner" || session.role === "manager";
}

/** The customer types of Paramètres › Types de clients (D-283), with the label of each code. A code no longer in
 * the list (should not happen) shows as itself. */
export function useCustomerTypes(): { types: CustomerType[]; labelOf: (code: string) => string } {
  const query = useListCustomerTypes();
  return useMemo(() => {
    const types = query.data ?? [];
    const labels = new Map(types.map((type) => [type.code, type.label]));
    return { types, labelOf: (code: string) => labels.get(code) ?? code };
  }, [query.data]);
}

/** The identification types of a customer (D-283), in the order the form offers them. */
export const ID_TYPES = ["tax_id", "cin", "passport", "residence_card"] as const;
