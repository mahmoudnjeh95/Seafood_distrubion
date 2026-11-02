import type { MyFieldPurchase } from "@frutti/api";

import type { ReceiptData } from "./receipt";

/** The receipt of a purchase the office has received: on "Mes achats" and right after it is sent. */
export function purchaseReceipt(purchase: MyFieldPurchase, company: string, by: string | undefined): ReceiptData {
  return {
    kind: "purchase",
    company,
    number: purchase.number,
    date: purchase.created_at,
    partyName: purchase.supplier?.name ?? purchase.proposed_supplier,
    by,
    lines: purchase.lines.map((line) => ({
      name: line.product?.name ?? line.proposed_product,
      quantity: line.received_quantity ?? line.declared_quantity,
      unitPrice: line.unit_cost,
      amount: line.amount,
    })),
    total: purchase.total,
    paid: purchase.paid,
    rest: purchase.rest,
  };
}
