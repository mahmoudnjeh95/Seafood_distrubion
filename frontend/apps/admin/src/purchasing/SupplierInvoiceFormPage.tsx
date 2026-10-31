import {
  ApiError,
  createSupplierInvoice,
  type Receipt,
  type SupplierInvoice,
  type SupplierInvoiceWrite,
  updateSupplierInvoice,
  useGetSupplierInvoice,
  useListReceipts,
  useListSuppliers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useMemo, useRef, useState } from "react";
import { Link, Navigate, useOutletContext, useParams, useSearchParams } from "react-router";

import { sum } from "../lib/decimal";
import { useLeave } from "../lib/embedded";
import { fieldErrors } from "../lib/errors";
import { canRecordReceipts, todayInTunis } from "../receipts/shared";
import { addDays, DEFAULT_PAYMENT_DAYS, idFrom, refreshPurchasing } from "./shared";

type Errors = Record<string, string>;
/** A receipt as the form lists it: from the receipts list, or already on the draft being changed. */
type Choice = { id: number; number: string; received_on: string; supplier_reference: string; amount: string };

function choiceOf(receipt: Receipt): Choice {
  return {
    id: receipt.id,
    number: receipt.number,
    received_on: receipt.received_on,
    supplier_reference: receipt.supplier_reference,
    amount: receipt.invoiced_total,
  };
}

/** New supplier invoice, or a draft being changed (`/achats/factures/:invoiceId/modifier`). */
export function SupplierInvoiceFormPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const { invoiceId } = useParams();
  const editingId = invoiceId === undefined ? null : idFrom(invoiceId);
  const existing = useGetSupplierInvoice(editingId ?? 0, { query: { enabled: editingId !== null, retry: false } });

  if (!canRecordReceipts(session)) return <Navigate to="/achats/factures" replace />;
  if (invoiceId !== undefined) {
    if (editingId !== null && existing.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
    if (!existing.data) {
      const missing = editingId === null || (existing.error instanceof ApiError && existing.error.status === 404);
      return (
        <EmptyState
          illustration="fish"
          title={missing ? t("admin.supplierInvoices.notFound") : t("common.serverUnreachable")}
        />
      );
    }
    // A posted invoice no longer changes: show it instead.
    if (existing.data.status !== "draft") return <Navigate to={`/achats/factures/${existing.data.id}`} replace />;
    return <InvoiceForm key={existing.data.id} invoice={existing.data} />;
  }
  return <InvoiceForm />;
}

function InvoiceForm({ invoice }: { invoice?: SupplierInvoice }) {
  const { t } = useTranslation();
  const { embedded, leave } = useLeave();
  const queryClient = useQueryClient();
  const formId = useId();
  const [params] = useSearchParams();

  const suppliers = useListSuppliers({ status: "all" });
  const [supplier, setSupplier] = useState(() =>
    invoice ? String(invoice.supplier.id) : String(idFrom(params.get("fournisseur")) ?? ""),
  );
  const [invoiceDate, setInvoiceDate] = useState(() => invoice?.invoice_date ?? todayInTunis());
  // Follows the invoice date (+30 days) until the person types one.
  const [dueDate, setDueDate] = useState(() => invoice?.due_date ?? "");
  const [supplierReference, setSupplierReference] = useState(invoice?.supplier_reference ?? "");
  const [notes, setNotes] = useState(invoice?.notes ?? "");
  // `?reception=12` (from the "Documents" page) ticks that receipt on a new invoice.
  const [chosen, setChosen] = useState<Set<number>>(() => {
    if (invoice) return new Set(invoice.receipts.map(({ receipt }) => receipt.id));
    const fromLink = idFrom(params.get("reception"));
    return new Set(fromLink === null ? [] : [fromLink]);
  });
  const [errors, setErrors] = useState<Errors>({});
  // Money already given to the supplier (at the port, advances) pays the invoice when it is validated (D-200).
  const [applyAdvances, setApplyAdvances] = useState(true);
  // "Valider et en faire une autre": stay on the form with the same supplier for the next invoice (D-200).
  const again = useRef(false);

  const shownDueDate = dueDate || addDays(invoiceDate, DEFAULT_PAYMENT_DAYS);
  const uninvoiced = useListReceipts(
    { supplier: Number(supplier), uninvoiced: true, limit: 200 },
    { query: { enabled: supplier !== "" } },
  );
  const choices = useMemo(() => {
    const own: Choice[] = invoice?.receipts.map(({ receipt, amount }) => ({ ...receipt, amount })) ?? [];
    const free = (uninvoiced.data?.results ?? []).map(choiceOf);
    return [...own, ...free].sort((a, b) => a.received_on.localeCompare(b.received_on) || a.id - b.id);
  }, [invoice, uninvoiced.data]);
  const total = sum(choices.filter((choice) => chosen.has(choice.id)).map((choice) => choice.amount));

  const save = useMutation({
    mutationFn: (payload: SupplierInvoiceWrite) =>
      invoice
        ? updateSupplierInvoice(invoice.id, {
            receipts: payload.receipts,
            invoice_date: payload.invoice_date,
            due_date: payload.due_date,
            supplier_reference: payload.supplier_reference,
            notes: payload.notes,
            post: payload.post,
          })
        : createSupplierInvoice(payload),
    onSuccess: async (saved) => {
      const message =
        saved.status !== "draft"
          ? "admin.supplierInvoices.form.createdPosted"
          : invoice
            ? "admin.supplierInvoices.form.saved"
            : "admin.supplierInvoices.form.createdDraft";
      toast.success(t(message, { number: saved.number }));
      await refreshPurchasing(queryClient);
      if (again.current) {
        again.current = false;
        setChosen(new Set());
        setSupplierReference("");
        setNotes("");
        setErrors({});
        return;
      }
      leave(`/achats/factures/${saved.id}`);
    },
    onError: (failure) => {
      again.current = false;
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.supplierInvoices.form.error") });
    },
  });

  function submit(post: boolean) {
    const found: Errors = {};
    if (!supplier) found.supplier = t("admin.supplierInvoices.form.required");
    if (!invoiceDate) found.invoice_date = t("admin.supplierInvoices.form.required");
    if (!shownDueDate) found.due_date = t("admin.supplierInvoices.form.required");
    else if (invoiceDate && shownDueDate < invoiceDate) found.due_date = t("admin.supplierInvoices.form.dueBeforeDate");
    if (supplier && chosen.size === 0) found.receipts = t("admin.supplierInvoices.form.noReceiptChosen");
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    save.mutate({
      supplier: Number(supplier),
      receipts: choices.filter((choice) => chosen.has(choice.id)).map((choice) => choice.id),
      invoice_date: invoiceDate,
      due_date: shownDueDate,
      supplier_reference: supplierReference.trim(),
      notes: notes.trim(),
      post,
      apply_advances: post && applyAdvances,
    });
  }

  const id = (name: string) => `${formId}-${name}`;
  const toggle = (receiptId: number, on: boolean) =>
    setChosen((current) => {
      const next = new Set(current);
      if (on) next.add(receiptId);
      else next.delete(receiptId);
      return next;
    });

  return (
    <>
      <PageHeader
        eyebrow={t("admin.nav.purchases")}
        title={
          invoice
            ? t("admin.supplierInvoices.form.editTitle", { number: invoice.number })
            : t("admin.supplierInvoices.form.createTitle")
        }
      />

      <form
        id={formId}
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          submit(false);
        }}
        noValidate
        className="flex flex-col gap-4"
      >
        <Card className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          <Field label={t("admin.supplierInvoices.form.supplier")} htmlFor={id("supplier")} error={errors.supplier}>
            <Select
              value={supplier}
              disabled={invoice !== undefined}
              onValueChange={(value) => {
                setSupplier(value);
                setChosen(new Set());
              }}
            >
              <SelectTrigger id={id("supplier")} aria-invalid={errors.supplier ? true : undefined}>
                <SelectValue placeholder={t("admin.supplierInvoices.form.choose")} />
              </SelectTrigger>
              <SelectContent>
                {(suppliers.data ?? [])
                  .filter((one) => one.is_active || String(one.id) === supplier)
                  .map((one) => (
                    <SelectItem key={one.id} value={String(one.id)}>
                      {one.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </Field>
          <Field
            label={t("admin.supplierInvoices.form.supplierReference")}
            htmlFor={id("supplier_reference")}
            error={errors.supplier_reference}
          >
            <Input
              id={id("supplier_reference")}
              value={supplierReference}
              maxLength={50}
              onChange={(event) => setSupplierReference(event.target.value)}
              autoComplete="off"
            />
          </Field>
          <Field
            label={t("admin.supplierInvoices.form.invoiceDate")}
            htmlFor={id("invoice_date")}
            error={errors.invoice_date}
          >
            <Input
              id={id("invoice_date")}
              type="date"
              max={todayInTunis()}
              value={invoiceDate}
              onChange={(event) => setInvoiceDate(event.target.value)}
              aria-invalid={errors.invoice_date ? true : undefined}
            />
          </Field>
          <Field label={t("admin.supplierInvoices.form.dueDate")} htmlFor={id("due_date")} error={errors.due_date}>
            <Input
              id={id("due_date")}
              type="date"
              min={invoiceDate}
              value={shownDueDate}
              onChange={(event) => setDueDate(event.target.value)}
              aria-invalid={errors.due_date ? true : undefined}
            />
            {!dueDate && <p className="text-[0.78rem] text-ink-2">{t("admin.supplierInvoices.form.dueDateHint")}</p>}
          </Field>
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.supplierInvoices.form.receipts")}</CardTitle>
          <p className="text-[0.85rem] text-ink-2">{t("admin.supplierInvoices.form.receiptsHint")}</p>
          {!supplier ? (
            <p className="text-ink-2">{t("admin.supplierInvoices.form.chooseSupplierFirst")}</p>
          ) : uninvoiced.isPending ? (
            <p className="text-ink-2">{t("common.loading")}</p>
          ) : choices.length === 0 ? (
            <p className="text-ink-2">{t("admin.supplierInvoices.form.noReceipts")}</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th className="w-10">
                    <span className="sr-only">{t("admin.supplierInvoices.form.receipts")}</span>
                  </Th>
                  <Th>{t("admin.supplierInvoices.form.receipt")}</Th>
                  <Th>{t("admin.supplierInvoices.form.receivedOn")}</Th>
                  <Th className="max-[720px]:hidden">{t("admin.supplierInvoices.form.deliveryNote")}</Th>
                  <Th numeric>{t("admin.supplierInvoices.form.amount")}</Th>
                </tr>
              </thead>
              <tbody>
                {choices.map((choice) => (
                  <tr key={choice.id}>
                    <Td>
                      <input
                        id={id(`receipt-${choice.id}`)}
                        type="checkbox"
                        checked={chosen.has(choice.id)}
                        onChange={(event) => toggle(choice.id, event.target.checked)}
                        aria-label={t("admin.supplierInvoices.form.receiptLabel", {
                          number: choice.number,
                          date: formatDate(choice.received_on),
                        })}
                        className="size-4 accent-coral"
                      />
                    </Td>
                    <Td className="num whitespace-nowrap">
                      <label htmlFor={id(`receipt-${choice.id}`)} className="font-semibold">
                        {choice.number}
                      </label>
                    </Td>
                    <Td className="num whitespace-nowrap">{formatDate(choice.received_on)}</Td>
                    <Td className="num max-[720px]:hidden">{choice.supplier_reference || "—"}</Td>
                    <Td numeric className="whitespace-nowrap">
                      {formatMoney(choice.amount)}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {errors.receipts && <p className="text-[0.78rem] font-semibold text-bad">{errors.receipts}</p>}
          <dl className="ms-auto">
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.supplierInvoices.form.total")}</dt>
            <dd className="num text-end font-bold">{formatMoney(total)}</dd>
          </dl>
        </Card>

        <Card>
          <Field label={t("admin.supplierInvoices.form.notes")} htmlFor={id("notes")} error={errors.notes}>
            <textarea
              id={id("notes")}
              rows={2}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
            />
          </Field>
        </Card>

        {(errors.detail ?? errors.status) && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail ?? errors.status}
          </p>
        )}

        {!invoice && (
          <label className="flex items-center justify-end gap-2 text-[0.9rem]">
            <input
              type="checkbox"
              checked={applyAdvances}
              onChange={(event) => setApplyAdvances(event.target.checked)}
            />
            {t("admin.supplierInvoices.form.applyAdvances")}
          </label>
        )}
        <p className="text-end text-[0.85rem] text-ink-2">{t("admin.supplierInvoices.form.postHint")}</p>
        <div className="flex flex-wrap justify-end gap-2">
          {embedded ? (
            <Button onClick={() => leave("/achats/factures")}>{t("admin.supplierInvoices.form.cancel")}</Button>
          ) : (
            <Button asChild>
              <Link to={invoice ? `/achats/factures/${invoice.id}` : "/achats/factures"}>
                {t("admin.supplierInvoices.form.cancel")}
              </Link>
            </Button>
          )}
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? t("admin.supplierInvoices.form.saving") : t("admin.supplierInvoices.form.saveDraft")}
          </Button>
          {!invoice && (
            <Button
              disabled={save.isPending}
              onClick={() => {
                again.current = true;
                submit(true);
              }}
            >
              {t("admin.supplierInvoices.form.saveAndAgain")}
            </Button>
          )}
          <Button variant="primary" disabled={save.isPending} onClick={() => submit(true)}>
            {t("admin.supplierInvoices.form.saveAndPost")}
          </Button>
        </div>
      </form>
    </>
  );
}
