import {
  type PaymentMethodEnum,
  recordSupplierPayment,
  type SupplierPaymentWrite,
  useListSupplierInvoices,
  useListSuppliers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  Field,
  Input,
  PageHeader,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useMemo, useState } from "react";
import { Link, Navigate, useNavigate, useOutletContext, useSearchParams } from "react-router";

import { subtract, sum } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { canRecordReceipts, todayInTunis } from "../receipts/shared";
import {
  type Allocations,
  allocationPayload,
  asTyped,
  byDueDate,
  compare,
  errorsByInvoice,
  hasAllocationProblem,
  spread,
} from "./allocation";
import { AllocationTable } from "./AllocationTable";
import { idFrom, refreshPurchasing } from "./shared";

const METHODS: readonly PaymentMethodEnum[] = ["cash", "cheque", "transfer", "bill", "other"];

type Errors = Record<string, string>;

/** Record a payment to a supplier and the invoices it settles. Owners and managers only; the server checks it. */
export function SupplierPaymentFormPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const formId = useId();
  const [params] = useSearchParams();
  // From an invoice page: `?fournisseur=3&facture=12` pays that invoice.
  const fromInvoice = idFrom(params.get("facture"));
  // From "Règlements fournisseurs" (D-192): `ligne` is the plan line this payment settles, with its amount and method.
  const planLine = idFrom(params.get("ligne"));
  const planAmount = planLine && fromInvoice ? (parseDecimalInput(params.get("montant") ?? "", 3) ?? "") : "";
  const planMethod = METHODS.find((one) => one === params.get("mode")) ?? "";

  const suppliers = useListSuppliers({ status: "all" });
  const [supplier, setSupplier] = useState(() => String(idFrom(params.get("fournisseur")) ?? ""));
  const [paidOn, setPaidOn] = useState(todayInTunis);
  const [amount, setAmount] = useState(asTyped(planAmount));
  const [method, setMethod] = useState<PaymentMethodEnum | "">(planAmount ? planMethod : "");
  const [reference, setReference] = useState(planAmount ? (params.get("ref") ?? "") : "");
  // The day a cheque or a traite may be cashed (D-159): asked only for those two.
  const [cashOn, setCashOn] = useState(planAmount ? (params.get("encaisse") ?? "") : "");
  const postDated = method === "cheque" || method === "bill";
  const [notes, setNotes] = useState("");
  const [allocations, setAllocations] = useState<Allocations>(
    planAmount && fromInvoice ? { [fromInvoice]: asTyped(planAmount) } : {},
  );
  // Until the person types an amount or an allocation, the invoice they came from is paid in full.
  // A plan line brings its own amount, so it counts as typed.
  const [touched, setTouched] = useState(planAmount !== "");
  const [errors, setErrors] = useState<Errors>({});
  const [lineErrors, setLineErrors] = useState<Record<number, string>>({});

  const open = useListSupplierInvoices(
    { supplier: Number(supplier), status: "open", limit: 200 },
    { query: { enabled: supplier !== "" } },
  );
  const invoices = useMemo(() => byDueDate(open.data?.results ?? []), [open.data]);
  const preset = touched ? undefined : invoices.find((invoice) => invoice.id === fromInvoice);
  const shownAmount = preset ? asTyped(preset.outstanding) : amount;
  const shownAllocations: Allocations = preset ? { [preset.id]: asTyped(preset.outstanding) } : allocations;

  const parsedAmount = parseDecimalInput(shownAmount.trim(), 3);
  const readable = allocationPayload(invoices, shownAllocations) ?? [];
  const allocated = sum(
    readable.filter(({ amount: value }) => !value.startsWith("-")).map(({ amount: value }) => value),
  );
  const remaining = parsedAmount && !parsedAmount.startsWith("-") ? subtract(parsedAmount, allocated) : null;
  const overAllocated = remaining !== null && remaining.startsWith("-");
  const allocationsError = overAllocated ? t("admin.supplierPayments.form.overAllocated") : errors.allocations;

  const save = useMutation({
    mutationFn: (payload: SupplierPaymentWrite) => recordSupplierPayment(payload),
    onSuccess: async (saved) => {
      toast.success(t("admin.supplierPayments.form.created", { number: saved.number }));
      await refreshPurchasing(queryClient);
      void navigate(fromInvoice ? `/achats/factures/${fromInvoice}` : "/achats/paiements");
    },
    onError: (failure, payload) => {
      const fromServer = fieldErrors(failure);
      setLineErrors(errorsByInvoice(fromServer, payload.allocations ?? []));
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.supplierPayments.form.error") });
    },
  });

  if (!canRecordReceipts(session)) return <Navigate to="/achats/paiements" replace />;

  function touch() {
    if (touched) return;
    // Keep what the preset showed, so typing changes it rather than starting from nothing.
    setAmount(shownAmount);
    setAllocations(shownAllocations);
    setTouched(true);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!supplier) found.supplier = t("admin.supplierPayments.form.required");
    if (!paidOn) found.paid_on = t("admin.supplierPayments.form.required");
    if (!method) found.method = t("admin.supplierPayments.form.required");
    if (parsedAmount === null || parsedAmount.startsWith("-")) found.amount = t("admin.supplierPayments.form.money");
    else if (compare(parsedAmount, "0") === 0) found.amount = t("admin.supplierPayments.form.positive");
    const payload = allocationPayload(invoices, shownAllocations);
    // A refused allocation already shows its message on its own row.
    const rowsRefused = payload === null || hasAllocationProblem(invoices, shownAllocations);
    setErrors(found);
    setLineErrors({});
    if (Object.keys(found).length > 0 || rowsRefused || overAllocated || !method || parsedAmount === null) return;
    save.mutate({
      supplier: Number(supplier),
      paid_on: paidOn,
      amount: parsedAmount,
      method,
      reference: reference.trim(),
      cash_on: postDated && cashOn ? cashOn : null,
      notes: notes.trim(),
      allocations: payload,
      plan_line: planAmount ? planLine : null,
    });
  }

  const id = (name: string) => `${formId}-${name}`;

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.supplierPayments.form.title")} />

      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          <Field label={t("admin.supplierPayments.form.supplier")} htmlFor={id("supplier")} error={errors.supplier}>
            <Select
              value={supplier}
              onValueChange={(value) => {
                setSupplier(value);
                setAllocations({});
                setTouched(true);
              }}
            >
              <SelectTrigger id={id("supplier")} aria-invalid={errors.supplier ? true : undefined}>
                <SelectValue placeholder={t("admin.supplierPayments.form.choose")} />
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
          <Field label={t("admin.supplierPayments.form.paidOn")} htmlFor={id("paid_on")} error={errors.paid_on}>
            <Input
              id={id("paid_on")}
              type="date"
              max={todayInTunis()}
              value={paidOn}
              onChange={(event) => setPaidOn(event.target.value)}
              aria-invalid={errors.paid_on ? true : undefined}
            />
          </Field>
          <Field label={t("admin.supplierPayments.form.amount")} htmlFor={id("amount")} error={errors.amount}>
            <Input
              id={id("amount")}
              inputMode="decimal"
              value={shownAmount}
              onChange={(event) => {
                touch();
                setAmount(event.target.value);
              }}
              aria-invalid={errors.amount ? true : undefined}
              autoComplete="off"
              className="num"
            />
          </Field>
          <Field label={t("admin.supplierPayments.form.method")} htmlFor={id("method")} error={errors.method}>
            <Select value={method} onValueChange={(value) => setMethod(value as PaymentMethodEnum)}>
              <SelectTrigger id={id("method")} aria-invalid={errors.method ? true : undefined}>
                <SelectValue placeholder={t("admin.supplierPayments.form.choose")} />
              </SelectTrigger>
              <SelectContent>
                {METHODS.map((choice) => (
                  <SelectItem key={choice} value={choice}>
                    {t(`admin.supplierPayments.method.${choice}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field
            label={t("admin.supplierPayments.form.reference")}
            htmlFor={id("reference")}
            error={errors.reference}
            className={postDated ? undefined : "col-span-full"}
          >
            <Input
              id={id("reference")}
              value={reference}
              maxLength={50}
              onChange={(event) => setReference(event.target.value)}
              autoComplete="off"
            />
          </Field>
          {postDated && (
            <Field label={t("admin.supplierPayments.form.cashOn")} htmlFor={id("cash_on")} error={errors.cash_on}>
              <Input
                id={id("cash_on")}
                type="date"
                min={paidOn}
                value={cashOn}
                onChange={(event) => setCashOn(event.target.value)}
                aria-invalid={errors.cash_on ? true : undefined}
              />
            </Field>
          )}
        </Card>

        <Card className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle className="mb-0">{t("admin.supplierPayments.form.invoices")}</CardTitle>
            {invoices.length > 0 && (
              <Button
                className="ms-auto"
                disabled={parsedAmount === null || parsedAmount.startsWith("-")}
                onClick={() => {
                  if (parsedAmount === null) return;
                  const shares = spread(
                    parsedAmount,
                    invoices.map((invoice) => invoice.outstanding),
                  );
                  touch();
                  setAllocations(
                    Object.fromEntries(invoices.map((invoice, index) => [invoice.id, asTyped(shares[index] ?? "")])),
                  );
                }}
              >
                {t("admin.supplierPayments.form.spread")}
              </Button>
            )}
          </div>
          <p className="text-[0.85rem] text-ink-2">{t("admin.supplierPayments.form.invoicesHint")}</p>
          {!supplier ? (
            <p className="text-ink-2">{t("admin.supplierPayments.form.chooseSupplierFirst")}</p>
          ) : open.isPending ? (
            <p className="text-ink-2">{t("common.loading")}</p>
          ) : invoices.length === 0 ? (
            <p className="text-ink-2">{t("admin.supplierPayments.form.noOpenInvoices")}</p>
          ) : (
            <AllocationTable
              idPrefix={formId}
              invoices={invoices}
              values={shownAllocations}
              errors={lineErrors}
              onChange={(invoiceId, value) => {
                touch();
                setAllocations((current) => ({ ...(touched ? current : shownAllocations), [invoiceId]: value }));
              }}
            />
          )}
          {allocationsError && <p className="text-[0.78rem] font-semibold text-bad">{allocationsError}</p>}
          <dl className="ms-auto flex flex-wrap gap-x-8 gap-y-2">
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">
                {t("admin.supplierPayments.form.amountTotal")}
              </dt>
              <dd className="num font-bold">
                {parsedAmount && !parsedAmount.startsWith("-") ? formatMoney(parsedAmount) : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">
                {t("admin.supplierPayments.form.allocatedTotal")}
              </dt>
              <dd className="num">{formatMoney(allocated)}</dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.supplierPayments.form.remaining")}</dt>
              <dd className="num">{remaining !== null && !overAllocated ? formatMoney(remaining) : "—"}</dd>
            </div>
          </dl>
        </Card>

        <Card>
          <Field label={t("admin.supplierPayments.form.notes")} htmlFor={id("notes")} error={errors.notes}>
            <textarea
              id={id("notes")}
              rows={2}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
            />
          </Field>
        </Card>

        {errors.detail && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <Button asChild>
            <Link to={fromInvoice ? `/achats/factures/${fromInvoice}` : "/achats/paiements"}>
              {t("admin.supplierPayments.form.cancel")}
            </Link>
          </Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {save.isPending ? t("admin.supplierPayments.form.saving") : t("admin.supplierPayments.form.save")}
          </Button>
        </div>
      </form>
    </>
  );
}
