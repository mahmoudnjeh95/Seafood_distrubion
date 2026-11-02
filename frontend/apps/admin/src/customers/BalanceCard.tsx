import { useGetCustomerBalance, useListInstruments, writeOffCustomerBalance } from "@frutti/api";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Dialog, Pill, Table, Td, Th } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { sum } from "../lib/decimal";
import { BalanceWriteOffDialog } from "../payments/BalanceWriteOffDialog";
import { Figure } from "../payments/Figure";
import { openItems } from "../payments/openItems";
import { amountToPay } from "../payments/toPay";

/** What the customer owes: "Total à régler" (the same number as the règlement form), what it is made of, ageing,
 * open sales, account history, and the button to collect (D-226). The owner can clear what is left to zero, given up
 * as a loss on the customer (D-252). */
export function BalanceCard({
  customer,
  canCollect,
  canClear,
}: {
  customer: { id: number; name: string };
  canCollect: boolean;
  canClear: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [clearing, setClearing] = useState(false);
  const query = useGetCustomerBalance(customer.id);
  // The effets received and not yet cashed: the same query as the règlement form, for the encours (D-210).
  const effets = useListInstruments(
    { customer: customer.id, direction: "received", status: "portfolio,deposited", limit: 200 },
    { query: { enabled: customer.id > 0 } },
  );
  const data = query.data;
  if (!data) return <p className="text-ink-2">{t("common.loading")}</p>;
  const credit = Number(data.balance) < 0;
  const toPay = amountToPay(data.balance);
  const items = openItems(data.open_sales);
  const invoiced = sum(items.filter((item) => item.kind === "invoice").map((item) => item.outstanding));
  const uninvoiced = sum(items.filter((item) => item.kind === "sale").map((item) => item.outstanding));
  const inPortfolio = sum((effets.data?.results ?? []).map((row) => row.amount));

  return (
    <>
      <Card className="col-span-full">
        <CardTitle>{t("admin.payments.balance.title")}</CardTitle>
        <div className="flex flex-wrap items-end justify-between gap-4">
          {/* flex-1: without a width the auto-fill grid shrinks to one column inside the flex row. */}
          <dl className="grid min-w-0 flex-1 grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-6 gap-y-3">
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">
                {t(credit ? "admin.payments.balance.creditHeld" : "admin.treasury.form.toPay")}
              </dt>
              <dd className="num text-[1.4rem] font-bold" data-testid="customer-balance">
                {formatMoney(credit ? data.credit : toPay)}
              </dd>
            </div>
            {!credit && (
              <>
                <Figure label={t("admin.payments.balance.invoicesOwed")} value={formatMoney(invoiced)} />
                <Figure label={t("admin.payments.balance.salesOwed")} value={formatMoney(uninvoiced)} />
                {Number(data.credit) > 0 && (
                  <Figure label={t("admin.payments.balance.unallocatedCredit")} value={formatMoney(data.credit)} />
                )}
              </>
            )}
            <Figure label={t("admin.treasury.form.inPortfolio")} value={formatMoney(inPortfolio)} />
            <Figure label={t("admin.treasury.form.exposure")} value={formatMoney(sum([toPay, inPortfolio]))} />
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
          {(canCollect || (canClear && !credit && toPay !== "0.000")) && (
            <div className="flex flex-wrap gap-2">
              {canCollect && (
                <Button variant="primary" asChild>
                  <Link to={`/reglements/nouveau?client=${customer.id}`}>{t("admin.payments.balance.collect")}</Link>
                </Button>
              )}
              {canClear && !credit && toPay !== "0.000" && (
                <Button variant="danger" onClick={() => setClearing(true)}>
                  {t("admin.payments.balance.clear")}
                </Button>
              )}
            </div>
          )}
        </div>
      </Card>

      <Dialog open={clearing} onOpenChange={setClearing}>
        <BalanceWriteOffDialog
          kind="customer"
          party={customer.name}
          owed={data.balance}
          onWrite={(body) => writeOffCustomerBalance(customer.id, body)}
          onDone={() => {
            setClearing(false);
            void queryClient.invalidateQueries();
          }}
        />
      </Dialog>

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
                    {entry.note && <span className="text-ink-2"> · {entry.note}</span>}
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

      {data.write_offs.length > 0 && (
        <Card className="col-span-full p-2">
          <CardTitle className="px-2 pt-2">
            {t("admin.payments.balance.writeOffs")} · {formatMoney(data.written_off_total)}
          </CardTitle>
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.payments.columns.date")}</Th>
                <Th>{t("admin.payments.balance.writeOffReason")}</Th>
                <Th>{t("admin.payments.balance.writeOffBy")}</Th>
                <Th numeric>{t("admin.payments.columns.amount")}</Th>
              </tr>
            </thead>
            <tbody>
              {data.write_offs.map((row) => (
                <tr key={row.id}>
                  <Td className="num whitespace-nowrap">{formatDate(row.written_on)}</Td>
                  <Td>{row.reason}</Td>
                  <Td>{row.created_by}</Td>
                  <Td numeric>{formatMoney(row.amount)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </>
  );
}
