import { addExpenseReceipt, ApiError, approveExpense, deleteExpense, rejectExpense, useGetExpense } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatDateTime, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  EmptyState,
  Field,
  Icon,
  PageHeader,
  Pill,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router";

import { sum } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { TreasuryTrace } from "../treasury/TreasuryTrace";
import { canWriteExpenses, EXPENSE_TONES, isOpen, refreshExpenses } from "./shared";

function Detail({ label, children, numeric = false }: { label: string; children: ReactNode; numeric?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("break-words", numeric && "num")}>{children}</dd>
    </div>
  );
}

/** One expense: what, how much, what it is charged to, its receipt, and the approval. */
export function ExpenseDetailPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { expenseId } = useParams();
  const id = Number(expenseId);
  const validId = Number.isInteger(id) && id > 0;
  const expense = useGetExpense(id, { query: { enabled: validId, retry: false } });
  const receiptId = useId();
  const reasonId = useId();
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectError, setRejectError] = useState("");

  const failed = (failure: unknown) => {
    const fromServer = fieldErrors(failure);
    toast.error(Object.values(fromServer)[0] ?? t("admin.expenses.actionError"));
  };
  const approve = useMutation({
    mutationFn: () => approveExpense(id),
    onSuccess: async (saved) => {
      toast.success(t("admin.expenses.detail.approvedToast", { number: saved.number }));
      await refreshExpenses(queryClient);
    },
    onError: failed,
  });
  const reject = useMutation({
    mutationFn: (reason: string) => rejectExpense(id, { reason }),
    onSuccess: async (saved) => {
      setRejecting(false);
      toast.success(t("admin.expenses.detail.rejectedToast", { number: saved.number }));
      await refreshExpenses(queryClient);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setRejectError(fromServer.reason ?? fromServer.detail ?? t("admin.expenses.actionError"));
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteExpense(id),
    onSuccess: async () => {
      toast.success(t("admin.expenses.detail.deletedToast"));
      await refreshExpenses(queryClient);
      void navigate("/charges");
    },
    onError: failed,
  });
  const receipt = useMutation({
    mutationFn: (file: File) => addExpenseReceipt(id, { receipt: file }),
    onSuccess: async () => {
      toast.success(t("admin.expenses.detail.receiptAdded"));
      await refreshExpenses(queryClient);
    },
    onError: failed,
  });

  const back = (
    <Link to="/charges" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.expenses.back")}
    </Link>
  );

  if (validId && expense.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!expense.data) {
    const missing = !validId || (expense.error instanceof ApiError && expense.error.status === 404);
    return (
      <>
        {back}
        <EmptyState illustration="mix" title={missing ? t("admin.expenses.notFound") : t("common.serverUnreachable")} />
      </>
    );
  }

  const data = expense.data;
  const none = t("admin.expenses.detail.none");
  const open = isOpen(data.status);
  const canWrite = canWriteExpenses(session);
  const isDayLabour = data.day_labour_id !== null;
  const mayAddReceipt = canWrite && (open || !data.receipt_url);

  return (
    <>
      {back}
      <PageHeader eyebrow={`${formatDate(data.spent_on)} · ${data.category.name}`} title={data.number}>
        <Pill tone={EXPENSE_TONES[data.status]}>{t(`admin.expenses.statuses.${data.status}`)}</Pill>
        {canWrite && open && (
          <>
            {data.status === "draft" && !isDayLabour && (
              <Button disabled={remove.isPending} onClick={() => remove.mutate()}>
                <Icon name="trash" />
                {t("admin.expenses.detail.delete")}
              </Button>
            )}
            {isDayLabour ? (
              <Button onClick={() => void navigate(`/charges/calendrier?jour=${data.spent_on}`)}>
                {t("admin.expenses.detail.openCalendar")}
              </Button>
            ) : (
              <Button onClick={() => void navigate(`/charges/${data.id}/modifier`)}>
                {t("admin.expenses.detail.edit")}
              </Button>
            )}
            <Button
              onClick={() => {
                setRejectReason("");
                setRejectError("");
                setRejecting(true);
              }}
            >
              {t("admin.expenses.detail.reject")}
            </Button>
            <Button variant="primary" disabled={approve.isPending} onClick={() => approve.mutate()}>
              <Icon name="check" />
              {t("admin.expenses.detail.approve")}
            </Button>
          </>
        )}
      </PageHeader>
      <TreasuryTrace source="expenses.expense" ids={[data.id]} />

      {data.status === "pending" && (
        <div role="note" className="flex items-start gap-3 rounded-card border border-line bg-warn-soft p-3">
          <span className="text-warn">
            <Icon name="alert" />
          </span>
          <span className="text-[0.9rem]">{t("admin.expenses.detail.pendingNote")}</span>
        </div>
      )}

      <Card>
        <CardTitle>{t("admin.expenses.detail.expense")}</CardTitle>
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-3">
          <Detail label={t("admin.expenses.detail.amount")} numeric>
            <b>{formatMoney(data.amount)}</b>
          </Detail>
          <Detail label={t("admin.expenses.detail.category")}>{data.category.name}</Detail>
          <Detail label={t("admin.expenses.detail.date")} numeric>
            {formatDate(data.spent_on)}
          </Detail>
          <Detail label={t("admin.expenses.detail.method")}>
            {t(`admin.expenses.methods.${data.payment_method}`)}
          </Detail>
          {isDayLabour && <Detail label={t("admin.expenses.detail.labourer")}>{data.labourer_name}</Detail>}
          {!isDayLabour && <Detail label={t("admin.expenses.detail.description")}>{data.description || none}</Detail>}
          {!isDayLabour && <Detail label={t("admin.expenses.detail.payee")}>{data.payee || none}</Detail>}
          <Detail label={t("admin.expenses.detail.charged")}>
            {data.batch ? (
              <Link to={`/stock/lots/${data.batch.id}`} className="font-semibold text-sea hover:underline">
                {t("admin.expenses.onLot", { number: data.batch.number, product: data.batch.product_name })}
              </Link>
            ) : data.truck ? (
              t("admin.expenses.onTruckDay", { name: data.truck.name, date: formatDate(data.spent_on) })
            ) : (
              t("admin.expenses.general")
            )}
          </Detail>
          <Detail label={t("admin.expenses.detail.enteredBy")}>{data.entered_by || none}</Detail>
          {data.decided_at && (
            <>
              <Detail label={t("admin.expenses.detail.decidedBy")}>{data.decided_by || none}</Detail>
              <Detail label={t("admin.expenses.detail.decidedAt")} numeric>
                {formatDateTime(data.decided_at)}
              </Detail>
            </>
          )}
          {data.notes && (
            <div className="col-span-full">
              <Detail label={t("admin.expenses.detail.notes")}>
                <span className="whitespace-pre-line">{data.notes}</span>
              </Detail>
            </div>
          )}
          {data.rejection_reason && (
            <div className="col-span-full">
              <Detail label={t("admin.expenses.detail.rejection")}>
                <span className="whitespace-pre-line">{data.rejection_reason}</span>
              </Detail>
            </div>
          )}
        </dl>
      </Card>

      {data.truck && (
        <Card className="p-2">
          <CardTitle className="px-2.5 pt-2">{t("admin.expenses.detail.split")}</CardTitle>
          {data.shares.length === 0 ? (
            <p className="px-2.5 pb-2 text-ink-2">{t("admin.expenses.detail.noLoad")}</p>
          ) : (
            <>
              <p className="px-2.5 text-[0.85rem] text-ink-2">{t("admin.expenses.detail.splitHint")}</p>
              <Table>
                <thead>
                  <tr>
                    <Th>{t("admin.expenses.detail.lot")}</Th>
                    <Th numeric>{t("admin.expenses.detail.loaded")}</Th>
                    <Th numeric>{t("admin.expenses.detail.share")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.shares.map((share) => (
                    <tr key={share.batch_id}>
                      <Td>
                        <Link
                          to={`/stock/lots/${share.batch_id}`}
                          className="num font-semibold text-sea hover:underline"
                        >
                          {share.batch_number}
                        </Link>{" "}
                        <span className="text-ink-2">{share.product_name}</span>
                      </Td>
                      <Td numeric className="whitespace-nowrap">
                        {formatQuantity(share.quantity)}
                      </Td>
                      <Td numeric className="whitespace-nowrap">
                        {formatMoney(share.amount)}
                      </Td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <Td className="font-semibold">{t("admin.expenses.detail.total")}</Td>
                    <Td numeric className="whitespace-nowrap font-semibold">
                      {formatQuantity(data.shares[0]?.day_quantity ?? "0")}
                    </Td>
                    <Td numeric className="whitespace-nowrap font-semibold">
                      {formatMoney(sum(data.shares.map((share) => share.amount)))}
                    </Td>
                  </tr>
                </tfoot>
              </Table>
            </>
          )}
        </Card>
      )}

      <Card className="flex flex-col gap-3">
        <CardTitle className="mb-0">{t("admin.expenses.detail.receipt")}</CardTitle>
        {data.receipt_url ? (
          data.receipt_type === "application/pdf" ? (
            <a
              href={data.receipt_url}
              target="_blank"
              rel="noreferrer"
              className="self-start font-semibold text-sea hover:underline"
            >
              {t("admin.expenses.detail.openPdf")}
            </a>
          ) : (
            <img
              src={data.receipt_url}
              alt={t("admin.expenses.detail.receiptAlt", { number: data.number })}
              className="max-h-80 w-auto self-start rounded-card border border-line object-contain"
            />
          )
        ) : (
          <p className="text-ink-2">{t("admin.expenses.detail.noReceipt")}</p>
        )}
        {mayAddReceipt && (
          <Field
            label={data.receipt_url ? t("admin.expenses.detail.replaceReceipt") : t("admin.expenses.detail.addReceipt")}
            htmlFor={receiptId}
          >
            <input
              id={receiptId}
              type="file"
              accept="image/jpeg,image/png,image/webp,application/pdf"
              disabled={receipt.isPending}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) receipt.mutate(file);
              }}
              className="self-start rounded-control border border-line bg-surface px-3 py-2 text-[0.9rem] text-ink"
            />
          </Field>
        )}
      </Card>

      {!open && <p className="text-[0.85rem] text-ink-2">{t("admin.expenses.detail.immutable")}</p>}

      <Dialog open={rejecting} onOpenChange={setRejecting}>
        <DialogContent>
          <DialogTitle>{t("admin.expenses.detail.rejectTitle", { number: data.number })}</DialogTitle>
          <DialogDescription>{t("admin.expenses.detail.rejectBody")}</DialogDescription>
          <form
            noValidate
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              reject.mutate(rejectReason);
            }}
          >
            <Field label={t("admin.expenses.detail.rejectReason")} htmlFor={reasonId} error={rejectError}>
              <textarea
                id={reasonId}
                rows={2}
                value={rejectReason}
                onChange={(event) => setRejectReason(event.target.value)}
                className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
              />
            </Field>
            <DialogFooter>
              <Button onClick={() => setRejecting(false)}>{t("admin.expenses.detail.keep")}</Button>
              <Button type="submit" variant="danger" disabled={reject.isPending}>
                {t("admin.expenses.detail.confirmReject")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
