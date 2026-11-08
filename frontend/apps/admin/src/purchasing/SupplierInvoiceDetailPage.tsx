import { ApiError, deleteSupplierInvoice, postSupplierInvoice, useGetSupplierInvoice } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  cn,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  EmptyState,
  Icon,
  PageHeader,
  Pill,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router";

import { canRecordReceipts } from "../receipts/shared";
import { refreshPurchasing, STATUS_TONE } from "./shared";

function Detail({ label, children, numeric = false }: { label: string; children: ReactNode; numeric?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("break-words", numeric && "num")}>{children}</dd>
    </div>
  );
}

export function SupplierInvoiceDetailPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canRecord = canRecordReceipts(session);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { invoiceId } = useParams();
  const id = Number(invoiceId);
  const validId = Number.isInteger(id) && id > 0;
  const invoice = useGetSupplierInvoice(id, { query: { enabled: validId, retry: false } });
  const [confirmDelete, setConfirmDelete] = useState(false);

  const post = useMutation({
    mutationFn: () => postSupplierInvoice(id),
    onSuccess: async (saved) => {
      toast.success(t("admin.supplierInvoices.detail.posted", { number: saved.number }));
      await refreshPurchasing(queryClient);
    },
    onError: () => toast.error(t("admin.supplierInvoices.detail.failed")),
  });
  const remove = useMutation({
    mutationFn: () => deleteSupplierInvoice(id),
    onSuccess: async () => {
      toast.success(t("admin.supplierInvoices.detail.deleted", { number: invoice.data?.number ?? "" }));
      await refreshPurchasing(queryClient);
      void navigate("/achats/factures");
    },
    onError: () => toast.error(t("admin.supplierInvoices.detail.failed")),
  });

  const back = (
    <Link to="/achats/factures" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.supplierInvoices.back")}
    </Link>
  );

  if (validId && invoice.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!invoice.data) {
    const missing = !validId || (invoice.error instanceof ApiError && invoice.error.status === 404);
    return (
      <>
        {back}
        <EmptyState
          illustration="fish"
          title={missing ? t("admin.supplierInvoices.notFound") : t("common.serverUnreachable")}
        />
      </>
    );
  }

  const data = invoice.data;
  const none = t("admin.supplierInvoices.detail.none");
  const isDraft = data.status === "draft";
  const isOpen = data.status === "posted" || data.status === "partly_paid";

  return (
    <>
      {back}
      <PageHeader eyebrow={`${formatDate(data.invoice_date)} · ${data.supplier.name}`} title={data.number}>
        <Pill tone={STATUS_TONE[data.status]}>{t(`admin.supplierInvoices.status.${data.status}`)}</Pill>
        {data.is_overdue && <Pill tone="bad">{t("admin.supplierInvoices.overdue")}</Pill>}
        {canRecord && isDraft && (
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(true)}>
              <Icon name="trash" />
              {t("admin.supplierInvoices.detail.delete")}
            </Button>
            <Button onClick={() => void navigate(`/achats/factures/${data.id}/modifier`)}>
              {t("admin.supplierInvoices.detail.edit")}
            </Button>
            <Button variant="primary" disabled={post.isPending} onClick={() => post.mutate()}>
              <Icon name="check" />
              {post.isPending ? t("admin.supplierInvoices.detail.posting") : t("admin.supplierInvoices.detail.post")}
            </Button>
          </>
        )}
        {canRecord && isOpen && (
          <Button
            variant="primary"
            onClick={() =>
              void navigate(`/achats/paiements/nouveau?fournisseur=${data.supplier.id}&facture=${data.id}`)
            }
          >
            <Icon name="cash" />
            {t("admin.supplierInvoices.detail.pay")}
          </Button>
        )}
      </PageHeader>

      {data.is_overdue && (
        <div role="note" className="flex items-start gap-3 rounded-card border border-line bg-bad-soft p-3">
          <span className="text-bad">
            <Icon name="alert" />
          </span>
          <div className="flex flex-col gap-0.5">
            <b>{t("admin.supplierInvoices.detail.overdueTitle")}</b>
            <span className="text-[0.9rem]">
              {t("admin.supplierInvoices.detail.overdueBody", {
                date: formatDate(data.due_date),
                amount: formatMoney(data.outstanding),
              })}
            </span>
          </div>
        </div>
      )}
      {isDraft && <p className="text-[0.9rem] text-ink-2">{t("admin.supplierInvoices.detail.draftNote")}</p>}

      <Card>
        <CardTitle>{t("admin.supplierInvoices.detail.invoice")}</CardTitle>
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-3">
          <Detail label={t("admin.supplierInvoices.detail.supplier")}>
            <Link to={`/fournisseurs/${data.supplier.id}`} className="font-semibold text-sea hover:underline">
              {data.supplier.name}
            </Link>
          </Detail>
          <Detail label={t("admin.supplierInvoices.detail.supplierReference")} numeric>
            {data.supplier_reference || none}
          </Detail>
          <Detail label={t("admin.supplierInvoices.detail.date")} numeric>
            {formatDate(data.invoice_date)}
          </Detail>
          <Detail label={t("admin.supplierInvoices.detail.due")} numeric>
            <span className={cn(data.is_overdue && "font-semibold text-bad")}>{formatDate(data.due_date)}</span>
          </Detail>
          <Detail label={t("admin.supplierInvoices.detail.createdBy")}>{data.created_by || none}</Detail>
          {data.posted_at && (
            <Detail label={t("admin.supplierInvoices.detail.postedBy")}>
              {data.posted_by || none} · <span className="num">{formatDateTime(data.posted_at)}</span>
            </Detail>
          )}
          {data.notes && (
            <div className="col-span-full">
              <Detail label={t("admin.supplierInvoices.detail.notes")}>
                <span className="whitespace-pre-line">{data.notes}</span>
              </Detail>
            </div>
          )}
        </dl>
      </Card>

      <Card className="p-2">
        <CardTitle className="px-2.5 pt-2">{t("admin.supplierInvoices.detail.receipts")}</CardTitle>
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.supplierInvoices.detail.receipt")}</Th>
              <Th>{t("admin.supplierInvoices.detail.receivedOn")}</Th>
              <Th className="max-[720px]:hidden">{t("admin.supplierInvoices.detail.deliveryNote")}</Th>
              <Th numeric>{t("admin.supplierInvoices.detail.amount")}</Th>
            </tr>
          </thead>
          <tbody>
            {data.receipts.map(({ receipt, amount }) => (
              <tr key={receipt.id}>
                <Td className="num whitespace-nowrap">
                  <Link to={`/achats/${receipt.id}`} className="font-semibold text-sea hover:underline">
                    {receipt.number}
                  </Link>
                </Td>
                <Td className="num whitespace-nowrap">{formatDate(receipt.received_on)}</Td>
                <Td className="num max-[720px]:hidden">{receipt.supplier_reference || none}</Td>
                <Td numeric className="whitespace-nowrap">
                  {formatMoney(amount)}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Card className="p-2">
        <CardTitle className="px-2.5 pt-2">{t("admin.supplierInvoices.detail.payments")}</CardTitle>
        {data.payments.length === 0 ? (
          <p className="px-2.5 pb-2 text-ink-2">{t("admin.supplierInvoices.detail.noPayments")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.supplierInvoices.detail.payment")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.supplierInvoices.detail.paidOn")}</Th>
                <Th>{t("admin.supplierInvoices.detail.method")}</Th>
                <Th numeric>{t("admin.supplierInvoices.detail.allocated")}</Th>
              </tr>
            </thead>
            <tbody>
              {data.payments.map(({ id: allocationId, payment, amount }) => (
                <tr key={allocationId}>
                  <Td className="num font-semibold whitespace-nowrap">{payment.number}</Td>
                  <Td className="num whitespace-nowrap max-[720px]:hidden">{formatDate(payment.paid_on)}</Td>
                  <Td>
                    {t(`admin.supplierPayments.method.${payment.method}`)}
                    {payment.reference && <span className="num text-ink-2"> · {payment.reference}</span>}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatMoney(amount)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <dl className="flex flex-wrap justify-end gap-x-8 gap-y-2 border-t border-line px-2.5 py-3">
          {(data.vat_total !== "0.000" || data.fiscal_stamp !== "0.000") && (
            <>
              <Detail label={t("admin.supplierInvoices.form.totalExclTax")} numeric>
                {formatMoney(data.total_excl_tax)}
              </Detail>
              <Detail label={t("admin.supplierInvoices.form.vatTotal")} numeric>
                {formatMoney(data.vat_total)}
              </Detail>
              <Detail label={t("admin.supplierInvoices.form.fiscalStamp")} numeric>
                {formatMoney(data.fiscal_stamp)}
              </Detail>
            </>
          )}
          <Detail label={t("admin.supplierInvoices.detail.total")} numeric>
            <b>{formatMoney(data.total)}</b>
          </Detail>
          {!isDraft && (
            <>
              <Detail label={t("admin.supplierInvoices.detail.paid")} numeric>
                {formatMoney(data.paid_amount)}
              </Detail>
              <Detail label={t("admin.supplierInvoices.detail.outstanding")} numeric>
                <span className={cn("font-semibold", data.is_overdue && "text-bad")}>
                  {formatMoney(data.outstanding)}
                </span>
              </Detail>
            </>
          )}
        </dl>
      </Card>

      {!isDraft && <p className="text-[0.85rem] text-ink-2">{t("admin.supplierInvoices.detail.immutable")}</p>}

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogTitle>{t("admin.supplierInvoices.detail.deleteTitle", { number: data.number })}</DialogTitle>
          <DialogDescription>{t("admin.supplierInvoices.detail.deleteBody")}</DialogDescription>
          <DialogFooter>
            <DialogClose asChild>
              <Button>{t("admin.supplierInvoices.detail.cancel")}</Button>
            </DialogClose>
            <Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {t("admin.supplierInvoices.detail.deleteConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
