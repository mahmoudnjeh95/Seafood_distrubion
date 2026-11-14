import type { SearchHit } from "@frutti/api";

/** Where each kind of hit opens. */
export function hitPath(hit: Pick<SearchHit, "kind" | "id">): string {
  switch (hit.kind) {
    case "customer":
      return `/clients/${hit.id}`;
    case "supplier":
      return `/fournisseurs/${hit.id}`;
    case "product":
      return `/stock/produits/${hit.id}`;
    case "lot":
      return `/stock/lots/${hit.id}`;
    case "sale":
      return `/ventes/${hit.id}`;
    case "invoice":
      return `/factures/${hit.id}`;
  }
}
