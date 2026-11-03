import type { MyFieldPurchase, SaleDetail } from "@frutti/api";

import type { QueuedDelivery } from "../queue";
import type { ReceiptData } from "./receipt";

/** The line under the totals of a delivery kept on the phone: the BL has its number, the office has not got it. */
export const KEPT_NOTE = "Pas encore envoyé au bureau : il part dès le retour du réseau.";

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

/** The receipt of a sale the office has: a sale on the road, or a BL of the load once delivered (with what was
 * delivered, D-281). A product taken off at the door (0 kg) is not printed. */
export function saleReceipt(sale: SaleDetail, company: string, by: string | undefined): ReceiptData {
  return {
    kind: "sale",
    company,
    number: sale.number,
    date: sale.delivered_at ?? sale.sold_at,
    partyName: sale.customer.name,
    by,
    lines: sale.lines
      .filter((line) => Number(line.quantity) > 0)
      .map((line) => ({
        name: line.product.name,
        quantity: line.quantity,
        unitPrice: line.unit_price,
        amount: line.amount,
      })),
    total: sale.total,
    paid: sale.amount_paid,
    rest: sale.amount_due,
  };
}

const millimes = (value: string) => Math.round(Number(value) * 1000);
const dinars = (value: number) => (value / 1000).toFixed(3);

/** The receipt of a BL delivered without signal (D-281): the kilos given at the door, priced as the BL. */
export function keptDeliveryReceipt(
  sale: SaleDetail,
  item: QueuedDelivery,
  company: string,
  by: string | undefined,
): ReceiptData {
  const changed = new Map(item.data.lines?.map((line) => [line.line, line.quantity]) ?? []);
  const lines = sale.lines.flatMap((line) => {
    const quantity = changed.get(line.id) ?? line.quantity;
    if (Number(quantity) <= 0) return [];
    const amount = Math.round(
      (Number(quantity) * millimes(line.unit_price) * (100 - Number(line.discount_rate))) / 100,
    );
    return [{ name: line.product.name, quantity, unitPrice: line.unit_price, amount }];
  });
  const total = lines.reduce((sum, line) => sum + line.amount, 0);
  const paid = millimes(item.data.amount_paid ?? "0");
  return {
    kind: "sale",
    company,
    number: sale.number,
    date: item.createdAt,
    partyName: sale.customer.name,
    by,
    lines: lines.map((line) => ({ ...line, amount: dinars(line.amount) })),
    total: dinars(total),
    paid: dinars(paid),
    rest: dinars(Math.max(total - paid, 0)),
    note: KEPT_NOTE,
  };
}
