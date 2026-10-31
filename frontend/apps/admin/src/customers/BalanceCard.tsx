import { useGetCustomerBalance } from "@frutti/api";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Pill, Table, Td, Th } from "@frutti/ui";
import { useState } from "react";
import { Link } from "react-router";

import { PaymentDialog } from "../payments/PaymentDialog";

/** What the customer owes: balance, ageing, open sales, account history, and the button to collect. */
export function BalanceCard({ customer, canCollect }: { customer: { id: number; name: string }; canCollect: boolean }) {
  const { t } = useTranslation();
  const query = useGetCustomerBalance(customer.id);
  const [paying, setPaying] = useState(false);
  const data = query.data;
  if (!data) return <p className="text-ink-2">{t("common.loading")}</p>;
  const credit = Number(data.balance) < 0;

  return (
    <>
      <Card className="col-span-full">
        <CardTitle>{t("admin.payments.balance.title")}</CardTitle>
        <div className="flex flex-wrap items-end justify-between gap-4">
          {/* flex-1: without a width the auto-fill grid shrinks to one column inside the flex row. */}
          <dl className="grid min-w-0 flex-1 grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-6 gap-y-3">
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">
                {t(credit ? "admin.payments.balance.creditHeld" : "admin.payments.balance.owes")}
              </dt>
              <dd className="num text-[1.4rem] font-bold" data-testid="customer-balance">
                {formatMoney(credit ? data.credit : data.balance)}
              </dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.payments.balance.available")}</dt>
              <dd className="num">{formatMoney(data.available_credit)}</dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.payments.balance.overdue")}</dt>
              <dd className="num">{formatMoney(data.overdue)}</dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.payments.ageing.d0_30")}</dt>
              <dd className="num">{formatMoney(data.ageing.d0_30)}</dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.payments.ageing.d31_60")}</dt>
              <dd className="num">{formatMoney(data.ageing.d31_60)}</dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.payments.ageing.d60_plus")}</dt>
              <dd className="num">{formatMoney(data.ageing.d60_plus)}</dd>
            </div>
          </dl>
          {canCollect && (
            <div className="flex flex-wrap gap-2">
              <Button asChild>
                <Link to={`/reglements/nouveau?client=${customer.id}`}>{t("admin.treasury.form.detailed")}</Link>
              </Button>
              <Button variant="primary" onClick={() => setPaying(true)}>
                {t("admin.payments.balance.collect")}
              </Button>
            </div>
          )}
        </div>
      </Card>

      {data.open_sales.length > 0 && (
        <Card className="col-span-full p-2">
          <CardTitle className="px-2 pt-2">{t("admin.payments.balance.openSales")}</CardTitle>
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.payments.balance.sale")}</Th>
                <Th>{t("admin.payments.balance.dueOn")}</Th>
                <Th numeric>{t("admin.payments.balance.owed")}</Th>
                <Th numeric>{t("admin.payments.balance.outstanding")}</Th>
              </tr>
            </thead>
            <tbody>
              {data.open_sales.map((row) => (
                <tr key={row.sale_id}>
                  <Td className="num font-semibold">
                    <Link to={`/ventes/${row.sale_id}`} className="text-sea hover:underline">
                      {row.number}
                    </Link>
                    {row.invoice_number && <span className="block text-[0.8rem] text-ink-2">{row.invoice_number}</span>}
                  </Td>
                  <Td className="num whitespace-nowrap">
                    {formatDate(row.due_on)}
                    {row.is_overdue && (
                      <Pill tone="bad" className="ms-2">
                        {t("admin.payments.balance.late")}
                      </Pill>
                    )}
                  </Td>
                  <Td numeric>{formatMoney(row.owed)}</Td>
                  <Td numeric className="font-semibold">
                    {formatMoney(row.outstanding)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <Card className="col-span-full p-2">
        <CardTitle className="px-2 pt-2">{t("admin.payments.balance.history")}</CardTitle>
        {data.history.length === 0 ? (
          <p className="px-2 pb-2 text-ink-2">{t("admin.payments.balance.noHistory")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.payments.columns.date")}</Th>
                <Th>{t("admin.payments.balance.entry")}</Th>
                <Th numeric>{t("admin.payments.columns.amount")}</Th>
                <Th numeric>{t("admin.payments.balance.runningBalance")}</Th>
              </tr>
            </thead>
            <tbody>
              {data.history.map((entry) => (
                <tr key={`${entry.kind}-${entry.object_id}`}>
                  <Td className="num whitespace-nowrap">{formatDate(entry.day)}</Td>
                  <Td>
                    {t(`admin.payments.balance.kinds.${entry.kind}`)} <span className="num">{entry.number}</span>
                    {entry.voided && (
                      <Pill tone="bad" className="ms-2">
                        {t("admin.payments.voided")}
                      </Pill>
                    )}
                  </Td>
                  <Td numeric>{formatMoney(entry.amount)}</Td>
                  <Td numeric>{formatMoney(entry.balance)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {paying && (
        <PaymentDialog
          customer={customer}
          {...(Number(data.balance) > 0 ? { owed: data.balance } : {})}
          onClose={() => setPaying(false)}
        />
      )}
    </>
  );
}
