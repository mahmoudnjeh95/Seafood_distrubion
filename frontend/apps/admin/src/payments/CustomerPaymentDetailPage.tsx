import {
  allocateCustomerPayment,
  type CustomerPaymentMethodEnum,
  useGetCustomerPayment,
  voidCustomerPayment,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, PageHeader, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { PdfButton } from "../lib/PdfButton";
import { compare } from "../purchasing/allocation";
import { statusTone } from "./listFilters";
import { EffetHistory, VoidReasonDialog } from "./ListParts";
import { canCollect, refreshAfterPayment } from "./shared";

/** One customer règlement (P9-T03b): its means, each cheque or traite with its state and history, the sales it
 * settled, the credit left ("Affecter le crédit", oldest sales first), the PDF receipt and "Annuler". */
export function CustomerPaymentDetailPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const queryClient = useQueryClient();
  const paymentId = Number(useParams().paymentId);
  const query = useGetCustomerPayment(paymentId);
  const [voiding, setVoiding] = useState(false);
  const canWrite = canCollect(session);
  const payment = query.data;
  const methodLabel = (method: string) => t(`admin.sales.methods.${method as CustomerPaymentMethodEnum}`);
  const allocate = useMutation({
    mutationFn: () => allocateCustomerPayment(paymentId, { allocations: null }),
    onSuccess: async () => {
      toast.success(t("admin.treasury.detail.allocated"));
      await refreshAfterPayment(queryClient);
    },
    onError: () => toast.error(t("admin.treasury.detail.allocateError")),
  });

  if (query.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!payment)
    return (
      <p role="alert" className="text-bad">
        {t("admin.treasury.detail.notFound")}
      </p>
    );
  const hasCredit = !payment.is_voided && compare(payment.unallocated, "0") > 0;

  return (
    <>
      <PageHeader eyebrow={t("admin.payments.title")} title={payment.number}>
        <div className="flex flex-wrap items-center gap-2">
          {payment.is_voided && <Pill tone="bad">{t("admin.payments.voided")}</Pill>}
          <PdfButton kind="receipt" id={payment.id} />
          {canWrite && hasCredit && (
            <Button disabled={allocate.isPending} onClick={() => allocate.mutate()}>
              {t("admin.treasury.detail.allocateCredit")}
            </Button>
          )}
          {canWrite && !payment.is_voided && (
            <Button variant="danger" onClick={() => setVoiding(true)}>
              {t("admin.payments.void.action")}
            </Button>
          )}
        </div>
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
          <Fact label={t("admin.payments.columns.customer")}>
            <Link to={`/clients/${payment.customer.id}`} className="font-semibold text-sea hover:underline">
              {payment.customer.name}
            </Link>
          </Fact>
          <Fact label={t("admin.payments.columns.date")}>{formatDate(payment.received_on)}</Fact>
          <Fact label={t("admin.treasury.form.receivedTotal")}>
            <span className="num text-lg font-bold">{formatMoney(payment.amount)}</span>
          </Fact>
          <Fact label={t("admin.treasury.form.credit")}>
            <span className="num">{formatMoney(payment.unallocated)}</span>
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
              <Th numeric>{t("admin.payments.columns.amount")}</Th>
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
                        {line.instrument.drawer && ` · ${line.instrument.drawer}`}
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
        <CardTitle>{t("admin.treasury.detail.settledSales")}</CardTitle>
        {payment.allocations.length === 0 ? (
          <p className="text-ink-2">{t("admin.treasury.detail.noAllocation")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.treasury.form.document")}</Th>
                <Th numeric>{t("admin.supplierPayments.form.allocation")}</Th>
              </tr>
            </thead>
            <tbody>
              {payment.allocations.map((allocation) => (
                <tr key={allocation.id}>
                  <Td className="num">
                    <Link to={`/ventes/${allocation.sale.id}`} className="font-semibold text-sea hover:underline">
                      {allocation.sale.number}
                    </Link>
                  </Td>
                  <Td numeric>{formatMoney(allocation.amount)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {voiding && (
        <VoidReasonDialog
          title={t("admin.payments.void.title", { number: payment.number })}
          body={t("admin.payments.void.body")}
          onClose={() => setVoiding(false)}
          onVoid={async (reason) => {
            await voidCustomerPayment(payment.id, { reason });
            toast.success(t("admin.payments.void.done", { number: payment.number }));
            await refreshAfterPayment(queryClient);
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
