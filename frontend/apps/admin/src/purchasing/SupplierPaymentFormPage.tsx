import {
  type PaymentMethodEnum,
  recordSupplierPayment,
  type SupplierPaymentWrite,
  useListBanks,
  useListSupplierInvoices,
  useListSuppliers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
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
import { ConfirmPaymentDialog } from "../payments/ConfirmPaymentDialog";
import {
  describeLine,
  errorsByLine,
  type LineProblem,
  lineProblems,
  linesPayload,
  linesTotal,
  newLine,
  type PaymentLine,
} from "../payments/lines";
import { PaymentLinesEditor } from "../payments/PaymentLinesEditor";
import { TotalsBar } from "../payments/TotalsBar";
import { canRecordReceipts, todayInTunis } from "../receipts/shared";
import {
  type Allocations,
  allocationPayload,
  asTyped,
  byDueDate,
  errorsByInvoice,
  hasAllocationProblem,
  spread,
} from "./allocation";
import { AllocationTable } from "./AllocationTable";
import { idFrom, refreshPurchasing } from "./shared";

const METHODS: readonly PaymentMethodEnum[] = ["cash", "cheque", "bill", "transfer", "other"];

type Errors = Record<string, string>;
type Line = PaymentLine<PaymentMethodEnum>;

/** Record a règlement to a supplier: its means line by line (cash, our cheques and traites, a transfer...) and
 * the invoices it settles (D-043, D-208). Owners and managers only; the server checks it. */
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
  const banks = useListBanks();
  const [supplier, setSupplier] = useState(() => String(idFrom(params.get("fournisseur")) ?? ""));
  const [paidOn, setPaidOn] = useState(todayInTunis);
  const [lines, setLines] = useState<Line[]>(() => [
    planAmount
      ? {
          ...newLine<PaymentMethodEnum>(planMethod, asTyped(planAmount)),
          number: params.get("ref") ?? "",
          reference: params.get("ref") ?? "",
          dueOn: params.get("encaisse") ?? "",
        }
      : newLine<PaymentMethodEnum>(),
  ]);
  const [notes, setNotes] = useState("");
  const [allocations, setAllocations] = useState<Allocations>(
    planAmount && fromInvoice ? { [fromInvoice]: asTyped(planAmount) } : {},
  );
  // Until the person types an amount or an allocation, the invoice they came from is paid in full.
  // A plan line brings its own amount, so it counts as typed.
  const [touched, setTouched] = useState(planAmount !== "");
  const [errors, setErrors] = useState<Errors>({});
  const [serverLineErrors, setServerLineErrors] = useState<Record<number, Record<string, string>>>({});
  const [checked, setChecked] = useState(false);
  const [invoiceErrors, setInvoiceErrors] = useState<Record<number, string>>({});
  const [confirming, setConfirming] = useState<SupplierPaymentWrite | null>(null);

  const open = useListSupplierInvoices(
    { supplier: Number(supplier), status: "open", limit: 200 },
    { query: { enabled: supplier !== "" } },
  );
  const invoices = useMemo(() => byDueDate(open.data?.results ?? []), [open.data]);
  const preset = touched ? undefined : invoices.find((invoice) => invoice.id === fromInvoice);
  // The invoice the person came from fills the first line's amount, once, until they type.
  const shownLines: Line[] =
    preset && lines.length === 1 && lines[0] && lines[0].amount === ""
      ? [{ ...lines[0], amount: asTyped(preset.outstanding) }]
      : lines;
  const shownAllocations: Allocations = preset ? { [preset.id]: asTyped(preset.outstanding) } : allocations;

  const total = linesTotal(shownLines);
  const readable = allocationPayload(invoices, shownAllocations) ?? [];
  const allocated = sum(
    readable.filter(({ amount: value }) => !value.startsWith("-")).map(({ amount: value }) => value),
  );
  const remaining = subtract(total, allocated);
  const overAllocated = remaining.startsWith("-");
  const allocationsError = overAllocated ? t("admin.supplierPayments.form.overAllocated") : errors.allocations;

  const problems = lineProblems(shownLines);
  const describe = (problem: LineProblem) => t(`admin.treasury.lines.problems.${problem}`);
  const lineErrors: Record<number, Record<string, string>> = {};
  shownLines.forEach((_line, index) => {
    const fromBrowser = checked
      ? Object.fromEntries(Object.entries(problems[index] ?? {}).map(([field, code]) => [field, describe(code)]))
      : {};
    lineErrors[index] = { ...(serverLineErrors[index] ?? {}), ...fromBrowser };
  });
  const bankRows = banks.data ?? [];

  const save = useMutation({
    mutationFn: (payload: SupplierPaymentWrite) => recordSupplierPayment(payload),
    onSuccess: async (saved) => {
      toast.success(t("admin.supplierPayments.form.created", { number: saved.number }));
      await refreshPurchasing(queryClient);
      void navigate(fromInvoice ? `/achats/factures/${fromInvoice}` : "/achats/paiements");
    },
    onError: (failure, payload) => {
      setConfirming(null);
      const fromServer = fieldErrors(failure);
      const { lines: byLine, rest } = errorsByLine(fromServer);
      setServerLineErrors(byLine);
      setInvoiceErrors(errorsByInvoice(rest, payload.allocations ?? []));
      setErrors(Object.keys(fromServer).length > 0 ? rest : { detail: t("admin.supplierPayments.form.error") });
    },
  });

  if (!canRecordReceipts(session)) return <Navigate to="/achats/paiements" replace />;

  function touch() {
    if (touched) return;
    // Keep what the preset showed, so typing changes it rather than starting from nothing.
    setLines(shownLines);
    setAllocations(shownAllocations);
    setTouched(true);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!supplier) found.supplier = t("admin.supplierPayments.form.required");
    if (!paidOn) found.paid_on = t("admin.supplierPayments.form.required");
    const payload = allocationPayload(invoices, shownAllocations);
    // A refused allocation already shows its message on its own row.
    const rowsRefused = payload === null || hasAllocationProblem(invoices, shownAllocations);
    setErrors(found);
    setChecked(true);
    setServerLineErrors({});
    setInvoiceErrors({});
    if (Object.keys(found).length > 0 || Object.keys(problems).length > 0 || rowsRefused || overAllocated) return;
    setConfirming({
      supplier: Number(supplier),
      paid_on: paidOn,
      amount: total,
      lines: linesPayload(shownLines),
      notes: notes.trim(),
      allocations: payload,
      plan_line: planAmount ? planLine : null,
    });
  }

  const id = (name: string) => `${formId}-${name}`;
  const supplierName = (suppliers.data ?? []).find((one) => String(one.id) === supplier)?.name ?? "";

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
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.treasury.lines.title")}</CardTitle>
          <p className="text-[0.85rem] text-ink-2">{t("admin.treasury.lines.supplierHint")}</p>
          <PaymentLinesEditor
            idPrefix={formId}
            lines={shownLines}
            onChange={(next) => {
              touch();
              setLines(next);
            }}
            methods={METHODS}
            methodLabel={(method) => t(`admin.supplierPayments.method.${method}`)}
            banks={bankRows}
            errors={lineErrors}
            issuedOn={paidOn}
          />
          {(errors.amount ?? errors.lines) && (
            <p className="text-[0.78rem] font-semibold text-bad">{errors.amount ?? errors.lines}</p>
          )}
        </Card>

        <Card className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle className="mb-0">{t("admin.supplierPayments.form.invoices")}</CardTitle>
            {invoices.length > 0 && (
              <Button
                className="ms-auto"
                disabled={total === "0.000"}
                onClick={() => {
                  const shares = spread(
                    total,
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
              errors={invoiceErrors}
              onChange={(invoiceId, value) => {
                touch();
                setAllocations((current) => ({ ...(touched ? current : shownAllocations), [invoiceId]: value }));
              }}
            />
          )}
          {allocationsError && <p className="text-[0.78rem] font-semibold text-bad">{allocationsError}</p>}
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

        {(errors.detail ?? errors.plan_line) && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail ?? errors.plan_line}
          </p>
        )}

        <TotalsBar
          total={total}
          allocated={allocated}
          remaining={remaining}
          overAllocated={overAllocated}
          labels={{
            total: t("admin.treasury.form.paidTotal"),
            allocated: t("admin.supplierPayments.form.allocatedTotal"),
            remaining: t("admin.treasury.form.advance"),
          }}
        >
          <Button asChild>
            <Link to={fromInvoice ? `/achats/factures/${fromInvoice}` : "/achats/paiements"}>
              {t("admin.supplierPayments.form.cancel")}
            </Link>
          </Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {save.isPending ? t("admin.supplierPayments.form.saving") : t("admin.supplierPayments.form.save")}
          </Button>
        </TotalsBar>
      </form>

      <ConfirmPaymentDialog
        open={confirming !== null}
        title={t("admin.treasury.form.confirmSupplier", { name: supplierName })}
        rows={[
          [t("admin.treasury.form.paidTotal"), formatMoney(total)],
          [t("admin.supplierPayments.form.allocatedTotal"), formatMoney(allocated)],
          [t("admin.treasury.form.advance"), formatMoney(remaining)],
        ]}
        means={shownLines.map((line) =>
          describeLine(line, {
            methodLabel: (method) => t(`admin.supplierPayments.method.${method}`),
            banks: bankRows,
            formatDate,
          }),
        )}
        pending={save.isPending}
        onCancel={() => setConfirming(null)}
        onConfirm={() => confirming && save.mutate(confirming)}
      />
    </>
  );
}
