import {
  ApiError,
  type CreditNote,
  deleteInvoice,
  type InvoiceDetail,
  type InvoiceLine,
  updateInvoice,
  useGetInvoice,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatQuantity,
  parseDecimalInput,
  useTranslation,
} from "@frutti/i18n";
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
  Input,
  MoneyInput,
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

import { DocumentFooter, DocumentHeader } from "../lib/DocumentFrame";
import { fieldErrors } from "../lib/errors";
import { PdfButton } from "../lib/PdfButton";
import { formatRate } from "../quotes/shared";
import { CertificateCard } from "./CertificateCard";
import { CreditNoteDialog } from "./CreditNoteDialog";
import { canInvoice, isZero, plainRate, refreshAfterInvoice, STATUS_TONES, toInput } from "./shared";

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className="break-words">{children}</dd>
    </div>
  );
}

function TotalRow({
  label,
  children,
  grand = false,
  note,
}: {
  label: string;
  children: ReactNode;
  grand?: boolean;
  note?: string;
}) {
  return (
    <div
      className={cn(
        "flex justify-between gap-4",
        grand && "mt-1 border-t-2 border-ink pt-1.5 text-[1.05rem] font-bold",
      )}
    >
      <dt>
        {label}
        {note && <span className="block text-[0.75rem] font-normal text-ink-2">{note}</span>}
      </dt>
      <dd className="num whitespace-nowrap">{children}</dd>
    </div>
  );
}

/** What the person typed on a draft: nothing typed means "what the settings and the product say". */
type DraftValues = {
  applyVat: boolean;
  rates: string[];
  amounts: Record<string, string>;
  stamp: string;
  fees: string;
  withholdingApplied: boolean;
  withholdingRate: string;
  notes: string;
};

function draftOf(invoice: InvoiceDetail): DraftValues {
  return {
    applyVat: invoice.apply_vat,
    rates: invoice.lines.map((line) => toInput(line.vat_rate)),
    amounts: Object.fromEntries(
      invoice.vat_lines.filter((row) => row.amount_overridden).map((row) => [row.rate, toInput(row.amount)]),
    ),
    stamp: invoice.fiscal_stamp_overridden ? toInput(invoice.fiscal_stamp) : "",
    fees: isZero(invoice.fees) ? "" : toInput(invoice.fees),
    withholdingApplied: invoice.withholding_applied,
    withholdingRate: invoice.withholding_rate_overridden ? toInput(invoice.withholding_rate) : "",
    notes: invoice.notes,
  };
}

class FormInvalid extends Error {}

/** The draft's form: VAT on or off, rate per line, VAT amount per rate, stamp, withholding. Freezes at issue. */
function DraftForm({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const formId = useId();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<DraftValues>(() => draftOf(invoice));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [issuing, setIssuing] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const set = (patch: Partial<DraftValues>) => setValues((current) => ({ ...current, ...patch }));

  /** The body of the PUT, plus the field errors found before sending. */
  function build(issueNow: boolean) {
    const found: Record<string, string> = {};
    const percent = (text: string, key: string) => {
      if (text.trim() === "") return null;
      const parsed = parseDecimalInput(text, 2);
      if (parsed === null || parsed.startsWith("-") || parsed.length > 6 || Number(parsed) > 100) {
        found[key] = t("admin.invoices.form.rateError");
        return null;
      }
      return parsed;
    };
    const money = (text: string, key: string) => {
      const parsed = parseDecimalInput(text, 3);
      if (parsed === null || parsed.startsWith("-")) {
        found[key] = t("admin.invoices.form.moneyError");
        return null;
      }
      return parsed;
    };
    // A rate goes to the server only when it was changed or was already typed: the others follow the settings.
    const lines = invoice.lines.map((line, index) => {
      const text = values.rates[index] ?? "";
      const changed = text.trim() !== toInput(line.vat_rate);
      const parsed = values.applyVat ? percent(text, `lines.${index}.vat_rate`) : null;
      return { vat_rate: values.applyVat && (changed || line.vat_rate_overridden) ? parsed : null };
    });
    const vatAmounts = values.applyVat
      ? Object.entries(values.amounts)
          .filter(([, text]) => text.trim() !== "")
          .map(([rate, text]) => ({ rate, amount: money(text, `vat_amounts.${rate}`) }))
      : [];
    const stamp = values.stamp.trim() === "" ? null : money(values.stamp, "fiscal_stamp");
    const fees = values.fees.trim() === "" ? null : money(values.fees, "fees");
    const withholdingRate = values.withholdingApplied ? percent(values.withholdingRate, "withholding_rate") : null;
    return {
      found,
      payload: {
        apply_vat: values.applyVat,
        lines,
        vat_amounts: vatAmounts,
        fiscal_stamp: stamp,
        fees,
        withholding_applied: values.withholdingApplied,
        withholding_rate: withholdingRate,
        notes: values.notes.trim(),
        issue_now: issueNow,
      },
    };
  }

  const save = useMutation({
    mutationFn: ({ issueNow }: { issueNow: boolean }) => {
      const { found, payload } = build(issueNow);
      if (Object.keys(found).length > 0) {
        setErrors(found);
        return Promise.reject(new FormInvalid());
      }
      return updateInvoice(invoice.id, payload);
    },
    onSuccess: async (saved, { issueNow }) => {
      setErrors({});
      setIssuing(false);
      toast.success(
        issueNow ? t("admin.invoices.detail.issued", { number: saved.number }) : t("admin.invoices.form.saved"),
      );
      await refreshAfterInvoice(queryClient);
    },
    onError: (failure) => {
      setIssuing(false);
      if (failure instanceof FormInvalid) return;
      const fromServer = fieldErrors(failure);
      if (Object.keys(fromServer).length > 0) setErrors(fromServer);
      else toast.error(t("admin.invoices.detail.actionError"));
    },
  });
  const discard = useMutation({
    mutationFn: () => deleteInvoice(invoice.id),
    onSuccess: async () => {
      toast.success(t("admin.invoices.detail.discarded"));
      await refreshAfterInvoice(queryClient);
      // One BL: back to it. A grouped invoice has several: back to the invoices.
      const [only] = invoice.sales;
      void navigate(invoice.sales.length === 1 && only ? `/ventes/${only.id}` : "/factures");
    },
    onError: () => toast.error(t("admin.invoices.detail.actionError")),
  });

  const busy = save.isPending || discard.isPending;
  const generalError = Object.entries(errors).find(
    ([key]) => !/^(lines\.|vat_amounts\.|fiscal_stamp$|fees$|withholding_rate$)/.test(key),
  )?.[1];

  return (
    <Card className="print:hidden">
      <CardTitle>{t("admin.invoices.form.title")}</CardTitle>
      <p className="mb-3 text-[0.85rem] text-ink-2">{t("admin.invoices.form.intro")}</p>

      <div className="flex flex-col gap-4">
        <label className="flex items-center gap-2.5 font-semibold">
          <input
            type="checkbox"
            className="size-4 accent-sea"
            checked={values.applyVat}
            onChange={(event) => set({ applyVat: event.target.checked })}
          />
          {t("admin.invoices.form.applyVat")}
        </label>
        {!values.applyVat && <p className="text-[0.85rem] text-ink-2">{t("admin.invoices.form.noVatNote")}</p>}
        {errors.apply_vat && (
          <p role="alert" className="text-[0.85rem] font-semibold text-bad">
            {errors.apply_vat}
          </p>
        )}

        {values.applyVat && (
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-[0.85rem] font-semibold">{t("admin.invoices.form.ratesTitle")}</legend>
            {invoice.lines.map((line, index) => (
              <div key={line.id} className="grid grid-cols-[minmax(0,1fr)_7rem] items-start gap-3">
                <div className="pt-2">
                  <span className="font-medium">{line.product_name}</span>
                  <div className="num text-[0.78rem] text-ink-2">
                    {t("admin.invoices.form.proposed", { rate: plainRate(line.default_vat_rate) })}
                  </div>
                </div>
                <Field
                  label={t("admin.invoices.form.lineRate", { name: line.product_name })}
                  htmlFor={`${formId}-rate-${line.id}`}
                  error={errors[`lines.${index}.vat_rate`]}
                  className="[&>label]:sr-only"
                >
                  <Input
                    id={`${formId}-rate-${line.id}`}
                    inputMode="decimal"
                    value={values.rates[index] ?? ""}
                    onChange={(event) =>
                      set({ rates: values.rates.map((rate, i) => (i === index ? event.target.value : rate)) })
                    }
                    aria-invalid={errors[`lines.${index}.vat_rate`] ? true : undefined}
                  />
                </Field>
              </div>
            ))}
            <p className="text-[0.78rem] text-ink-2">{t("admin.invoices.form.ratesHint")}</p>
          </fieldset>
        )}

        {values.applyVat && invoice.vat_lines.some((row) => !isZero(row.rate)) && (
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-[0.85rem] font-semibold">{t("admin.invoices.form.amountsTitle")}</legend>
            {invoice.vat_lines
              .filter((row) => !isZero(row.rate))
              .map((row) => (
                <Field
                  key={row.rate}
                  label={t("admin.invoices.form.amountAt", { rate: plainRate(row.rate) })}
                  htmlFor={`${formId}-amount-${row.rate}`}
                  error={errors[`vat_amounts.${row.rate}`]}
                >
                  <MoneyInput
                    id={`${formId}-amount-${row.rate}`}
                    inputMode="decimal"
                    value={values.amounts[row.rate] ?? ""}
                    placeholder={toInput(row.computed_amount)}
                    onChange={(event) => set({ amounts: { ...values.amounts, [row.rate]: event.target.value } })}
                    aria-invalid={errors[`vat_amounts.${row.rate}`] ? true : undefined}
                  />
                </Field>
              ))}
            <p className="text-[0.78rem] text-ink-2">{t("admin.invoices.form.amountsHint")}</p>
          </fieldset>
        )}

        <Field label={t("admin.invoices.form.stamp")} htmlFor={`${formId}-stamp`} error={errors.fiscal_stamp}>
          <MoneyInput
            id={`${formId}-stamp`}
            inputMode="decimal"
            value={values.stamp}
            placeholder={toInput(invoice.settings_fiscal_stamp ?? invoice.fiscal_stamp)}
            onChange={(event) => set({ stamp: event.target.value })}
            aria-invalid={errors.fiscal_stamp ? true : undefined}
          />
        </Field>

        <Field label={t("admin.invoices.form.fees")} htmlFor={`${formId}-fees`} error={errors.fees}>
          <MoneyInput
            id={`${formId}-fees`}
            inputMode="decimal"
            value={values.fees}
            placeholder="0,000"
            onChange={(event) => set({ fees: event.target.value })}
            aria-invalid={errors.fees ? true : undefined}
          />
        </Field>

        <div className="flex flex-col gap-2">
          <label className="flex items-center gap-2.5 font-semibold">
            <input
              type="checkbox"
              className="size-4 accent-sea"
              checked={values.withholdingApplied}
              onChange={(event) => set({ withholdingApplied: event.target.checked })}
            />
            {t("admin.invoices.form.withholding")}
          </label>
          {values.withholdingApplied && (
            <Field
              label={t("admin.invoices.form.withholdingRate")}
              htmlFor={`${formId}-withholding`}
              error={errors.withholding_rate}
            >
              <Input
                id={`${formId}-withholding`}
                inputMode="decimal"
                value={values.withholdingRate}
                placeholder={toInput(invoice.settings_withholding_rate ?? invoice.withholding_rate)}
                onChange={(event) => set({ withholdingRate: event.target.value })}
                aria-invalid={errors.withholding_rate ? true : undefined}
              />
            </Field>
          )}
        </div>

        <Field label={t("admin.invoices.form.notes")} htmlFor={`${formId}-notes`}>
          <Input
            id={`${formId}-notes`}
            value={values.notes}
            maxLength={500}
            onChange={(event) => set({ notes: event.target.value })}
          />
        </Field>

        {generalError && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {generalError}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => save.mutate({ issueNow: false })}>
            {save.isPending && !issuing ? t("admin.invoices.form.saving") : t("admin.invoices.form.save")}
          </Button>
          <Button variant="primary" disabled={busy} onClick={() => setIssuing(true)}>
            <Icon name="check" />
            {t("admin.invoices.detail.issue")}
          </Button>
          <Button variant="danger" disabled={busy} onClick={() => setDiscarding(true)}>
            {t("admin.invoices.detail.discard")}
          </Button>
        </div>
      </div>

      <Dialog open={issuing} onOpenChange={setIssuing}>
        <DialogContent>
          <DialogTitle>{t("admin.invoices.detail.issueTitle")}</DialogTitle>
          <DialogDescription>{t("admin.invoices.detail.issueBody")}</DialogDescription>
          <DialogFooter>
            <Button onClick={() => setIssuing(false)}>{t("admin.invoices.detail.keep")}</Button>
            <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate({ issueNow: true })}>
              {t("admin.invoices.detail.confirmIssue")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={discarding} onOpenChange={setDiscarding}>
        <DialogContent>
          <DialogTitle>{t("admin.invoices.detail.discardTitle")}</DialogTitle>
          <DialogDescription>{t("admin.invoices.detail.discardBody")}</DialogDescription>
          <DialogFooter>
            <Button onClick={() => setDiscarding(false)}>{t("admin.invoices.detail.keep")}</Button>
            <Button variant="danger" disabled={discard.isPending} onClick={() => discard.mutate()}>
              {t("admin.invoices.detail.confirmDiscard")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function LinesTable({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const vat = invoice.apply_vat;
  return (
    <Table>
      <thead>
        <tr>
          <Th>{t("admin.invoices.document.product")}</Th>
          <Th numeric>{t("admin.invoices.document.quantity")}</Th>
          <Th numeric>{vat ? t("admin.invoices.document.unitPriceExcl") : t("admin.invoices.document.unitPrice")}</Th>
          {vat && <Th numeric>{t("admin.invoices.document.vatRate")}</Th>}
          <Th numeric>{vat ? t("admin.invoices.document.amountExcl") : t("admin.invoices.document.amount")}</Th>
        </tr>
      </thead>
      <tbody>
        {invoice.lines.map((line: InvoiceLine) => (
          <tr key={line.id}>
            <Td>
              {line.product_name}
              <div className="num text-[0.78rem] text-ink-2">
                {line.product_reference}
                {line.lots ? ` · ${line.lots}` : ""}
                {invoice.sales.length > 1 ? ` · ${line.sale_number}` : ""}
              </div>
            </Td>
            <Td numeric className="whitespace-nowrap">
              {formatQuantity(line.quantity)}
            </Td>
            <Td numeric className="whitespace-nowrap">
              {formatMoney(vat ? line.unit_price_excl_tax : line.unit_price)}
            </Td>
            {vat && (
              <Td numeric className="whitespace-nowrap">
                {isZero(line.vat_rate) ? t("admin.invoices.document.exempt") : formatRate(line.vat_rate)}
                {line.vat_rate_overridden && (
                  <span className="block text-[0.72rem] text-ink-2">{t("admin.invoices.document.typed")}</span>
                )}
              </Td>
            )}
            <Td numeric className="font-semibold whitespace-nowrap">
              {formatMoney(vat ? line.amount_excl_tax : line.amount)}
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function Totals({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const stamp = !isZero(invoice.fiscal_stamp);
  const showWithholding = invoice.withholding_applied && !isZero(invoice.withholding_rate);
  return (
    <dl
      className="ms-auto mt-3.5 flex w-[min(360px,100%)] flex-col gap-1"
      aria-label={t("admin.invoices.document.totals")}
    >
      {!isZero(invoice.discount_total) && (
        <>
          <TotalRow label={t("admin.invoices.document.subtotal")}>{formatMoney(invoice.subtotal)}</TotalRow>
          <TotalRow label={t("admin.invoices.document.discount")}>−{formatMoney(invoice.discount_total)}</TotalRow>
        </>
      )}
      {invoice.apply_vat ? (
        <>
          <TotalRow label={t("admin.invoices.document.totalExcl")}>{formatMoney(invoice.total_excl_tax)}</TotalRow>
          {invoice.vat_lines.map((row) => (
            <TotalRow
              key={row.rate}
              label={
                isZero(row.rate)
                  ? t("admin.invoices.document.vatExempt")
                  : t("admin.invoices.document.vatAt", { rate: plainRate(row.rate) })
              }
              note={
                row.amount_overridden
                  ? t("admin.invoices.document.vatTyped", { computed: formatMoney(row.computed_amount) })
                  : undefined
              }
            >
              {formatMoney(row.amount)}
            </TotalRow>
          ))}
        </>
      ) : (
        <TotalRow label={t("admin.invoices.document.totalNoVat")}>{formatMoney(invoice.total_excl_tax)}</TotalRow>
      )}
      {stamp && <TotalRow label={t("admin.invoices.document.stamp")}>{formatMoney(invoice.fiscal_stamp)}</TotalRow>}
      {!isZero(invoice.fees) && (
        <TotalRow label={t("admin.invoices.document.fees")}>{formatMoney(invoice.fees)}</TotalRow>
      )}
      <TotalRow
        label={invoice.apply_vat ? t("admin.invoices.document.totalIncl") : t("admin.invoices.document.total")}
        grand
      >
        {formatMoney(invoice.total_incl_tax)}
      </TotalRow>
      {showWithholding && (
        <>
          <TotalRow label={t("admin.invoices.document.withholding", { rate: plainRate(invoice.withholding_rate) })}>
            −{formatMoney(invoice.withholding_amount)}
          </TotalRow>
          <TotalRow label={t("admin.invoices.document.netToPay")}>{formatMoney(invoice.net_to_pay)}</TotalRow>
        </>
      )}
      {!isZero(invoice.credited_total) && (
        <>
          <TotalRow label={t("admin.invoices.document.credited")}>−{formatMoney(invoice.credited_total)}</TotalRow>
          <TotalRow label={t("admin.invoices.document.remaining")}>{formatMoney(invoice.remaining_to_pay)}</TotalRow>
        </>
      )}
    </dl>
  );
}

function CreditNotesCard({ notes }: { notes: readonly CreditNote[] }) {
  const { t } = useTranslation();
  if (notes.length === 0) return null;
  return (
    <Card>
      <CardTitle>{t("admin.invoices.detail.creditNotes")}</CardTitle>
      <ul className="flex flex-col gap-2">
        {notes.map((note) => (
          <li key={note.id} className="flex flex-wrap items-baseline gap-x-3 border-b border-line pb-2 last:border-0">
            <span className="num font-semibold">{note.number}</span>
            <Pill tone="sea">{t(`admin.invoices.creditKinds.${note.kind}`)}</Pill>
            <span className="num text-ink-2">{formatDate(note.issued_on)}</span>
            <span className="num ms-auto font-semibold">{formatMoney(note.net_amount)}</span>
            <PdfButton kind="credit_note" id={note.id} variant="ghost" className="print:hidden" />
            <span className="w-full text-[0.85rem] text-ink-2">
              {note.reason}
              {note.stock !== "none" && ` · ${t(`admin.invoices.creditDialog.stocks.${note.stock}`)}`}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** One invoice, printable. A draft shows the form to adapt VAT, stamp and withholding; an issued one is frozen. */
export function InvoicePage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const { invoiceId } = useParams();
  const id = Number(invoiceId);
  const validId = Number.isInteger(id) && id > 0;
  const query = useGetInvoice(id, { query: { enabled: validId, retry: false } });
  const [crediting, setCrediting] = useState(false);

  const back = (
    <Link to="/factures" className="text-[0.85rem] font-semibold text-sea hover:underline print:hidden">
      {t("admin.invoices.back")}
    </Link>
  );

  if (validId && query.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!query.data) {
    const missing = !validId || (query.error instanceof ApiError && query.error.status === 404);
    return (
      <>
        {back}
        <EmptyState illustration="mix" title={missing ? t("admin.invoices.notFound") : t("common.serverUnreachable")} />
      </>
    );
  }

  const invoice = query.data;
  const writer = canInvoice(session);
  const draft = invoice.status === "draft";
  const title = invoice.number || t("admin.invoices.draftTitle");
  // Mount the form again from the saved values after every save.
  const formKey = [
    invoice.id,
    invoice.total_incl_tax,
    invoice.apply_vat,
    invoice.notes,
    invoice.fiscal_stamp,
    invoice.fees,
    invoice.withholding_rate,
    invoice.withholding_applied,
    invoice.lines.map((line) => line.vat_rate).join("/"),
    invoice.vat_lines.map((row) => row.amount).join("/"),
  ].join("|");

  return (
    <>
      {back}
      <PageHeader eyebrow={t("admin.invoices.title")} title={title}>
        <Pill tone={STATUS_TONES[invoice.status]}>{t(`admin.invoices.statuses.${invoice.status}`)}</Pill>
        {!draft && <PdfButton kind="invoice" id={invoice.id} className="print:hidden" />}
        {!draft && (
          <Button onClick={() => window.print()} className="print:hidden">
            <Icon name="receipt" />
            {t("admin.invoices.detail.print")}
          </Button>
        )}
        {writer && invoice.status === "issued" && (
          <Button variant="danger" className="print:hidden" onClick={() => setCrediting(true)}>
            {t("admin.invoices.detail.creditNote")}
          </Button>
        )}
      </PageHeader>

      <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] items-start gap-4 max-[1000px]:grid-cols-1 print:block">
        <Card role="region" aria-label={t("admin.invoices.document.label", { number: title })}>
          <DocumentHeader
            seller={invoice.seller}
            logoUrl={session.organization.logo_url}
            title={t("admin.documents.frame.invoice")}
            number={title}
            date={invoice.issued_on}
            // The customer's code and phone are not frozen on the invoice: they are read from the customer.
            party={{ ...invoice.bill_to, reference: invoice.customer.reference, phone: invoice.customer.phone }}
            meta={
              <>
                <p className="num">
                  {t("admin.invoices.document.sale")} {invoice.sales.map((sale) => sale.number).join(", ")}
                </p>
                {invoice.due_on && (
                  <p className="num">
                    {t("admin.invoices.document.dueOn")} {formatDate(invoice.due_on)}
                  </p>
                )}
              </>
            }
          />
          <LinesTable invoice={invoice} />
          <Totals invoice={invoice} />
          {invoice.notes && (
            <p className="mt-4 border-t border-line pt-3 text-[0.9rem] whitespace-pre-line">{invoice.notes}</p>
          )}
          <DocumentFooter seller={invoice.seller} />
        </Card>

        <div className="flex flex-col gap-4">
          {draft && writer && <DraftForm key={formKey} invoice={invoice} />}
          {draft && !writer && (
            <Card className="print:hidden">
              <p className="text-[0.9rem]">{t("admin.invoices.readOnly")}</p>
            </Card>
          )}
          <Card className="print:hidden">
            <CardTitle>{t("admin.invoices.detail.followUp")}</CardTitle>
            <p role="note" className="mb-4 rounded-chip bg-surface-2 px-3 py-2 text-[0.9rem]">
              {t(`admin.invoices.detail.statusNotes.${invoice.status}`)}
            </p>
            <dl className="flex flex-col gap-3">
              <Detail label={t("admin.invoices.detail.customer")}>
                <Link to={`/clients/${invoice.customer.id}`} className="font-semibold text-ink hover:underline">
                  {invoice.customer.name}
                </Link>
              </Detail>
              <Detail label={t("admin.invoices.detail.sale")}>
                {invoice.sales.map((sale) => (
                  <Link
                    key={sale.id}
                    to={`/ventes/${sale.id}`}
                    className="num me-2 font-semibold text-sea hover:underline"
                  >
                    {sale.number}
                  </Link>
                ))}
              </Detail>
              <Detail label={t("admin.invoices.detail.vatMode")}>
                {invoice.apply_vat
                  ? invoice.prices_include_vat
                    ? t("admin.invoices.detail.vatIncluded")
                    : t("admin.invoices.detail.vatOnTop")
                  : t("admin.invoices.detail.vatNone")}
              </Detail>
              {invoice.settings_valid_from && draft && (
                <Detail label={t("admin.invoices.detail.settings")}>
                  {t("admin.invoices.detail.settingsLine", {
                    date: formatDate(invoice.settings_valid_from),
                    vat: plainRate(invoice.settings_vat_rate ?? "0"),
                  })}
                </Detail>
              )}
              <Detail label={t("admin.invoices.detail.createdBy")}>
                {invoice.created_by || "—"} · <span className="num">{formatDateTime(invoice.created_at)}</span>
              </Detail>
              {invoice.issued_at && (
                <Detail label={t("admin.invoices.detail.issuedBy")}>
                  {invoice.issued_by || "—"} · <span className="num">{formatDateTime(invoice.issued_at)}</span>
                </Detail>
              )}
              <Detail label={t("admin.invoices.detail.einvoice")}>
                {t(`admin.invoices.einvoice.${invoice.einvoice_status}`)}
                {invoice.einvoice_reference && <span className="num block">{invoice.einvoice_reference}</span>}
              </Detail>
            </dl>
          </Card>
          <CertificateCard invoice={invoice} canWrite={writer} />
          <CreditNotesCard notes={invoice.credit_notes} />
        </div>
      </div>

      {crediting && <CreditNoteDialog invoice={invoice} onClose={() => setCrediting(false)} />}
    </>
  );
}
