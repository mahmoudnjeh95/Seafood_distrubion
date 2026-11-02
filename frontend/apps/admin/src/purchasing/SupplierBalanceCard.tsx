import { useGetSupplierBalance, writeOffSupplierBalance } from "@frutti/api";
import { formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Dialog, cn } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link } from "react-router";

import { BalanceWriteOffDialog } from "../payments/BalanceWriteOffDialog";
import { amountToPay, creditHeld } from "../payments/toPay";
import { compare } from "./allocation";

function Line({ label, children, tone }: { label: string; children: ReactNode; tone?: "bad" | "warn" }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="text-ink-2">{label}</dt>
      <dd
        className={cn(
          "num whitespace-nowrap",
          tone === "bad" && "font-semibold text-bad",
          tone === "warn" && "text-warn",
        )}
      >
        {children}
      </dd>
    </div>
  );
}

/** What the company owes a supplier for goods (invoices − payments), on the supplier page. Trade payable
 * only: a partner's capital and profit share are separate balances (D-040). The owner can clear what is owed to zero,
 * given up as a gain on the supplier (D-252). */
export function SupplierBalanceCard({
  supplierId,
  supplierName,
  canRecord,
  canClear,
}: {
  supplierId: number;
  supplierName: string;
  canRecord: boolean;
  canClear: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [clearing, setClearing] = useState(false);
  const balance = useGetSupplierBalance(supplierId);
  const data = balance.data;

  return (
    <>
      <Card className="col-span-full">
        <CardTitle>{t("admin.supplierBalance.title")}</CardTitle>
        {balance.isPending ? (
          <p className="text-ink-2">{t("common.loading")}</p>
        ) : !data ? (
          <p role="alert" className="text-bad">
            {t("common.serverUnreachable")}
          </p>
        ) : (
          <div className="grid gap-x-8 gap-y-4 min-[720px]:grid-cols-[1fr_1.4fr]">
            <div className="flex flex-col gap-1">
              <span className="text-[0.78rem] font-semibold text-ink-2">{t("admin.treasury.form.toPay")}</span>
              <span className="num text-[1.6rem] font-bold" data-testid="supplier-to-pay">
                {formatMoney(amountToPay(data.balance))}
              </span>
              {compare(creditHeld(data.balance), "0") > 0 && (
                <span className="text-[0.85rem] text-ink-2">
                  {t("admin.supplierBalance.creditHeld", { amount: formatMoney(creditHeld(data.balance)) })}
                </span>
              )}
              <span className="text-[0.85rem] text-ink-2">{t("admin.supplierBalance.balanceHint")}</span>
              <div className="mt-2 flex flex-wrap gap-2">
                {canRecord && (
                  <>
                    <Button asChild variant="primary">
                      <Link to={`/achats/paiements/nouveau?fournisseur=${supplierId}`}>
                        {t("admin.supplierBalance.newPayment")}
                      </Link>
                    </Button>
                    <Button asChild>
                      <Link to={`/achats/factures/nouvelle?fournisseur=${supplierId}`}>
                        {t("admin.supplierBalance.newInvoice")}
                      </Link>
                    </Button>
                  </>
                )}
                {canClear && compare(data.balance, "0") > 0 && (
                  <Button variant="danger" onClick={() => setClearing(true)}>
                    {t("admin.supplierBalance.clear")}
                  </Button>
                )}
              </div>
            </div>
            <div>
              <dl className="flex flex-col divide-y divide-line">
                <Line label={t("admin.supplierBalance.invoiced")}>{formatMoney(data.invoiced)}</Line>
                <Line label={t("admin.supplierBalance.paid")}>{formatMoney(data.paid)}</Line>
                <Line label={t("admin.supplierBalance.outstanding")}>{formatMoney(data.outstanding)}</Line>
                {data.overdue_invoices > 0 && (
                  <Line label={t("admin.supplierBalance.overdue", { count: data.overdue_invoices })} tone="bad">
                    {formatMoney(data.overdue)}
                  </Line>
                )}
                {compare(data.unallocated, "0") > 0 && (
                  <Line label={t("admin.supplierBalance.unallocated")} tone="warn">
                    {formatMoney(data.unallocated)}
                  </Line>
                )}
                {data.draft_invoices > 0 && (
                  <Line label={t("admin.supplierBalance.drafts", { count: data.draft_invoices })}>
                    {formatMoney(data.draft_total)}
                  </Line>
                )}
                {data.uninvoiced_receipts > 0 && (
                  <Line label={t("admin.supplierBalance.uninvoiced", { count: data.uninvoiced_receipts })}>
                    {formatMoney(data.uninvoiced_total)}
                  </Line>
                )}
              </dl>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.85rem] font-semibold">
                <Link to={`/achats/factures?fournisseur=${supplierId}`} className="text-sea hover:underline">
                  {t("admin.supplierBalance.invoices")}
                </Link>
                <Link to={`/achats/paiements?fournisseur=${supplierId}`} className="text-sea hover:underline">
                  {t("admin.supplierBalance.payments")}
                </Link>
              </div>
            </div>
            <p className="col-span-full text-[0.85rem] text-ink-2">{t("admin.supplierBalance.separate")}</p>
          </div>
        )}
      </Card>

      {data && (
        <Dialog open={clearing} onOpenChange={setClearing}>
          <BalanceWriteOffDialog
            kind="supplier"
            party={supplierName}
            owed={data.balance}
            onWrite={(body) => writeOffSupplierBalance(supplierId, body)}
            onDone={() => {
              setClearing(false);
              void queryClient.invalidateQueries();
            }}
          />
        </Dialog>
      )}
    </>
  );
}
