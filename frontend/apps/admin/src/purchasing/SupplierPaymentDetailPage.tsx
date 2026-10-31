import { type SupplierPaymentMethodEnum, useGetSupplierPayment, voidSupplierPayment } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Dialog, PageHeader, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { EmailButton } from "../lib/EmailButton";
import { PdfButton } from "../lib/PdfButton";
import { statusTone } from "../payments/listFilters";
import { EffetHistory, VoidReasonDialog } from "../payments/ListParts";
import { canRecordReceipts } from "../receipts/shared";
import { AllocateDialog } from "./AllocateDialog";
import { compare } from "./allocation";
import { refreshPurchasing } from "./shared";

/** One supplier règlement (P9-T03b): its means, each cheque or traite with its state and history, the invoices it
 * settled, the advance left ("Affecter"), and "Annuler" with a reason (D-211). */
export function SupplierPaymentDetailPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const queryClient = useQueryClient();
  const paymentId = Number(useParams().paymentId);
  const query = useGetSupplierPayment(paymentId);
  const [allocating, setAllocating] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const canWrite = canRecordReceipts(session);
  const payment = query.data;
  const methodLabel = (method: string) => t(`admin.supplierPayments.method.${method as SupplierPaymentMethodEnum}`);

  if (query.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!payment)
    return (
      <p role="alert" className="text-bad">
        {t("admin.treasury.detail.notFound")}
      </p>
    );
  const hasAdvance = compare(payment.unallocated_amount, "0") > 0;

  return (
    <>
      <PageHeader eyebrow={t("admin.supplierPayments.title")} title={payment.number}>
        <PdfButton kind="supplier_receipt" id={payment.id} />
        <EmailButton kind="supplier_receipt" id={payment.id} />
        {payment.is_voided ? (
          <Pill tone="bad">{t("admin.payments.voided")}</Pill>
        ) : (
          canWrite && (
            <div className="flex gap-2">
              {hasAdvance && (
                <Button onClick={() => setAllocating(true)}>{t("admin.supplierPayments.allocate")}</Button>
              )}
              <Button variant="danger" onClick={() => setVoiding(true)}>
                {t("admin.payments.void.action")}
              </Button>
            </div>
          )
        )}
      </PageHeader>

      {payment.is_voided && (
        <p role="status" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.9rem] text-bad">
          {t("admin.treasury.detail.voidedBy", {
            who: payment.voided_by || "—",
            when: payment.voided_at ? formatDateTime(payment.voided_at) : "",
            reason: payment.void_reason,
          })}
        </p>
      )}

      <Card>
        <dl className="grid grid-cols-4 gap-4 max-[720px]:grid-cols-2">
          <Fact label={t("admin.supplierPayments.columns.supplier")}>
            <Link to={`/fournisseurs/${payment.supplier.id}`} className="font-semibold text-sea hover:underline">
              {payment.supplier.name}
            </Link>
          </Fact>
          <Fact label={t("admin.supplierPayments.columns.date")}>{formatDate(payment.paid_on)}</Fact>
          <Fact label={t("admin.treasury.form.paidTotal")}>
            <span className="num text-lg font-bold">{formatMoney(payment.amount)}</span>
          </Fact>
          <Fact label={t("admin.treasury.form.advance")}>
            <span className="num">{formatMoney(payment.unallocated_amount)}</span>
          </Fact>
          <Fact label={t("admin.treasury.detail.method")}>{methodLabel(payment.method)}</Fact>
          <Fact label={t("admin.treasury.detail.createdBy")}>
            {payment.created_by || "—"} · {formatDateTime(payment.created_at)}
          </Fact>
          {payment.notes && (
            <Fact label={t("admin.supplierPayments.form.notes")} wide>
              {payment.notes}
            </Fact>
          )}
        </dl>
      </Card>

      <Card>
        <CardTitle>{t("admin.treasury.lines.title")}</CardTitle>
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.treasury.lines.method")}</Th>
              <Th>{t("admin.treasury.detail.paper")}</Th>
              <Th>{t("admin.treasury.lines.dueOn")}</Th>
              <Th>{t("admin.treasury.detail.state")}</Th>
              <Th numeric>{t("admin.supplierPayments.columns.amount")}</Th>
            </tr>
          </thead>
          <tbody>
            {payment.lines.map((line) => (
              <tr key={line.id}>
                <Td className="font-semibold">{methodLabel(line.method)}</Td>
                <Td>
                  {line.instrument ? (
                    <>
                      <span className="num">{line.instrument.number}</span>
                      <span className="text-ink-2">
                        {" "}
                        · {line.instrument.bank_code || t("admin.treasury.detail.bankMissing")}
                      </span>
                      <div className="mt-1">
                        <EffetHistory events={line.instrument.events} />
                      </div>
                    </>
                  ) : (
                    <span className="num">{line.reference || "—"}</span>
                  )}
                </Td>
                <Td className="num whitespace-nowrap">{line.instrument ? formatDate(line.instrument.due_on) : "—"}</Td>
                <Td>
                  {line.instrument ? (
                    <Pill tone={statusTone(line.instrument.status)}>
                      {t(`admin.treasury.status.${line.instrument.status}`)}
                    </Pill>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td numeric className="whitespace-nowrap">
                  {formatMoney(line.amount)}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Card>
        <CardTitle>{t("admin.treasury.detail.allocations")}</CardTitle>
        {payment.allocations.length === 0 ? (
          <p className="text-ink-2">{t("admin.treasury.detail.noAllocation")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.supplierPayments.form.invoice")}</Th>
                <Th>{t("admin.supplierPayments.form.invoiceDate")}</Th>
                <Th numeric>{t("admin.supplierPayments.form.allocation")}</Th>
              </tr>
            </thead>
            <tbody>
              {payment.allocations.map((allocation) => (
                <tr key={allocation.id}>
                  <Td className="num">
                    <Link
                      to={`/achats/factures/${allocation.invoice.id}`}
                      className="font-semibold text-sea hover:underline"
                    >
                      {allocation.invoice.number}
                    </Link>
                    {allocation.invoice.supplier_reference && (
                      <span className="text-ink-2"> · {allocation.invoice.supplier_reference}</span>
                    )}
                  </Td>
                  <Td className="num">{formatDate(allocation.invoice.invoice_date)}</Td>
                  <Td numeric>{formatMoney(allocation.amount)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Dialog open={allocating} onOpenChange={(open) => !open && setAllocating(false)}>
        {allocating && <AllocateDialog payment={payment} onDone={() => setAllocating(false)} />}
      </Dialog>
      {voiding && (
        <VoidReasonDialog
          title={t("admin.payments.void.title", { number: payment.number })}
          body={t("admin.treasury.detail.supplierVoidBody")}
          onClose={() => setVoiding(false)}
          onVoid={async (reason) => {
            await voidSupplierPayment(payment.id, { reason });
            toast.success(t("admin.payments.void.done", { number: payment.number }));
            await refreshPurchasing(queryClient);
          }}
        />
      )}
    </>
  );
}

function Fact({ label, wide = false, children }: { label: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={wide ? "col-span-full" : undefined}>
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
