import type { CustomerBalance } from "@frutti/api";

import { sum, toThousandths } from "../lib/decimal";

/** What a règlement can settle: a whole invoice (spread over its BLs, oldest first, by the server) or a BL that
 * is on no invoice. */
export type OpenItem = {
  key: string;
  kind: "invoice" | "sale";
  id: number;
  number: string;
  /** The BLs of an invoice. */
  sales: string[];
  day: string;
  dueOn: string;
  ageDays: number;
  isOverdue: boolean;
  outstanding: string;
};

/** The customer's open sales gathered by invoice, the one due first first. */
export function openItems(openSales: CustomerBalance["open_sales"]): OpenItem[] {
  const items = new Map<string, OpenItem>();
  for (const sale of openSales) {
    const key = sale.invoice_id ? `invoice-${sale.invoice_id}` : `sale-${sale.sale_id}`;
    const item = items.get(key);
    if (item) {
      item.sales.push(sale.number);
      item.outstanding = sum([item.outstanding, sale.outstanding]);
      if (sale.due_on < item.dueOn) item.dueOn = sale.due_on;
      item.ageDays = Math.max(item.ageDays, sale.age_days);
      item.isOverdue ||= sale.is_overdue;
      continue;
    }
    items.set(key, {
      key,
      kind: sale.invoice_id ? "invoice" : "sale",
      id: sale.invoice_id ?? sale.sale_id,
      number: sale.invoice_id ? sale.invoice_number : sale.number,
      sales: [sale.number],
      day: sale.document_date,
      dueOn: sale.due_on,
      ageDays: sale.age_days,
      isOverdue: sale.is_overdue,
      outstanding: sale.outstanding,
    });
  }
  return [...items.values()]
    .filter((item) => toThousandths(item.outstanding) > 0n)
    .sort((a, b) => a.dueOn.localeCompare(b.dueOn) || a.day.localeCompare(b.day) || a.key.localeCompare(b.key));
}
