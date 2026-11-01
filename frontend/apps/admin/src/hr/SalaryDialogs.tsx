import {
  addSalaryPrime,
  adjustSalaryRecord,
  recordSalaryPayment,
  type SalaryPaymentKindEnum,
  type SalaryPaymentMethodEnum,
  type SalaryRecord,
  type PatchedSalaryRecordUpdate,
  updateSalaryRecord,
} from "@frutti/api";
import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Input,
  MoneyInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";

import { percentOf, subtract, sum } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { todayInTunis } from "../receipts/shared";
import { PAYMENT_KINDS, PAYMENT_METHODS, refreshHr } from "./shared";

const typed = (decimal: string) => decimal.replace(".", ",");

function Detail({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
      {message}
    </p>
  );
}

// ---- Change a draft salary: bonus, overtime, deductions ----

type RecordField = "base_salary" | "bonus" | "overtime" | "deductions";
const RECORD_FIELDS: readonly RecordField[] = ["base_salary", "bonus", "overtime", "deductions"];

/** Change a draft salary record; gross, employer contribution and net are previewed as the server computes them. */
export function SalaryRecordDialog({ record, onDone }: { record: SalaryRecord; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [values, setValues] = useState<Record<RecordField, string>>({
    base_salary: typed(record.base_salary),
    bonus: typed(record.bonus),
    overtime: typed(record.overtime),
    deductions: typed(record.deductions),
  });
  const [ownRate, setOwnRate] = useState(typed(record.employee_cnss_rate));
  const [notes, setNotes] = useState(record.notes);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const parsed = Object.fromEntries(
    RECORD_FIELDS.map((field) => [field, parseDecimalInput(values[field].trim() || "0", 3)]),
  ) as Record<RecordField, string | null>;
  const readable = RECORD_FIELDS.every((field) => parsed[field] !== null && !parsed[field]?.startsWith("-"));
  const gross = readable ? sum([parsed.base_salary ?? "0", parsed.bonus ?? "0", parsed.overtime ?? "0"]) : null;
  const parsedOwnRate = parseDecimalInput(ownRate.trim() || "0", 2);
  const ownRateOk = parsedOwnRate !== null && !parsedOwnRate.startsWith("-") && Number(parsedOwnRate) <= 100;
  const employer = gross === null ? null : percentOf(gross, record.cnss_rate);
  const own = gross === null || !ownRateOk ? null : percentOf(gross, parsedOwnRate ?? "0");
  const net = gross === null || own === null ? null : subtract(subtract(gross, own), parsed.deductions ?? "0");

  const save = useMutation({
    mutationFn: (payload: PatchedSalaryRecordUpdate) => updateSalaryRecord(record.id, payload),
    onSuccess: async () => {
      toast.success(t("admin.hr.record.saved"));
      await refreshHr(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.hr.record.error") });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    for (const field of RECORD_FIELDS) {
      if (parsed[field] === null || parsed[field]?.startsWith("-")) found[field] = t("admin.hr.form.invalidAmount");
    }
    if (!ownRateOk) found.employee_cnss_rate = t("admin.hr.form.invalidRate");
    if (net !== null && net.startsWith("-")) found.deductions = t("admin.hr.record.deductionsTooHigh");
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    save.mutate({
      base_salary: parsed.base_salary ?? "0",
      bonus: parsed.bonus ?? "0",
      overtime: parsed.overtime ?? "0",
      deductions: parsed.deductions ?? "0",
      employee_cnss_rate: parsedOwnRate ?? "0",
      notes: notes.trim(),
    });
  }

  return (
    <DialogContent className="w-[min(560px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.hr.record.editTitle", { name: record.employee.name })}</DialogTitle>
      <DialogDescription className="sr-only">
        {t("admin.hr.record.editTitle", { name: record.employee.name })}
      </DialogDescription>
      <form id={formId} onSubmit={submit} noValidate className="grid grid-cols-2 gap-4 max-[560px]:grid-cols-1">
        {RECORD_FIELDS.map((field) => (
          <Field key={field} label={t(`admin.hr.record.${field}`)} htmlFor={`${formId}-${field}`} error={errors[field]}>
            <MoneyInput
              id={`${formId}-${field}`}
              inputMode="decimal"
              value={values[field]}
              onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
              aria-invalid={errors[field] ? true : undefined}
              autoComplete="off"
              className="num"
            />
          </Field>
        ))}
        <Field
          label={t("admin.hr.record.employeeCnssRate")}
          htmlFor={`${formId}-own-rate`}
          error={errors.employee_cnss_rate}
          className="col-span-full"
        >
          <Input
            id={`${formId}-own-rate`}
            inputMode="decimal"
            value={ownRate}
            onChange={(event) => setOwnRate(event.target.value)}
            aria-invalid={errors.employee_cnss_rate ? true : undefined}
            autoComplete="off"
            className="num"
          />
        </Field>
        <Field label={t("admin.hr.record.notes")} htmlFor={`${formId}-notes`} className="col-span-full">
          <Input id={`${formId}-notes`} value={notes} onChange={(event) => setNotes(event.target.value)} />
        </Field>
        <dl className="col-span-full flex flex-wrap gap-x-8 gap-y-2">
          <div>
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.hr.record.gross")}</dt>
            <dd className="num font-bold">{gross === null ? "—" : formatMoney(gross)}</dd>
          </div>
          <div>
            <dt className="text-[0.78rem] font-semibold text-ink-2">
              {t("admin.hr.record.employerCnss", { rate: typed(record.cnss_rate) })}
            </dt>
            <dd className="num">{employer === null ? "—" : formatMoney(employer)}</dd>
          </div>
          <div>
            <dt className="text-[0.78rem] font-semibold text-ink-2">
              {t("admin.hr.record.employeeCnss", { rate: ownRate })}
            </dt>
            <dd className="num">{own === null ? "—" : `− ${formatMoney(own)}`}</dd>
          </div>
          <div>
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.hr.record.net")}</dt>
            <dd className="num font-bold">{net === null || net.startsWith("-") ? "—" : formatMoney(net)}</dd>
          </div>
        </dl>
      </form>
      <Detail message={errors.detail ?? errors.status} />
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.hr.form.cancel")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {save.isPending ? t("admin.hr.form.saving") : t("admin.hr.form.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

// ---- Pay a salary ----

/** Record cash paid for one approved salary: the amount is proposed as what is still owed. */
export function SalaryPaymentDialog({ record, onDone }: { record: SalaryRecord; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [paidOn, setPaidOn] = useState(todayInTunis);
  const [amount, setAmount] = useState(typed(record.outstanding));
  const [method, setMethod] = useState<SalaryPaymentMethodEnum>("cash");
  const [kind, setKind] = useState<SalaryPaymentKindEnum>("salary");
  const [confirmOverpay, setConfirmOverpay] = useState(false);
  const [reference, setReference] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  // An advance above what the month still owes goes through only once the office confirms it (D-234).
  const overpay = (value: string) => kind === "advance" && subtract(record.outstanding, value).startsWith("-");

  const save = useMutation({
    mutationFn: (value: string) =>
      recordSalaryPayment({
        employee: record.employee.id,
        paid_on: paidOn,
        amount: value,
        method,
        kind,
        confirm_overpay: confirmOverpay && overpay(value),
        reference: reference.trim(),
        allocations: [{ salary_record: record.id, amount: value }],
      }),
    onSuccess: async (saved) => {
      toast.success(t("admin.hr.pay.recorded", { number: saved.number }));
      await refreshHr(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      // The only allocation is the amount typed: its error shows under the amount.
      const amountError = fromServer["allocations.0.amount"] ?? fromServer.allocations ?? fromServer.amount;
      setErrors(
        Object.keys(fromServer).length > 0
          ? { ...fromServer, ...(amountError ? { amount: amountError } : {}) }
          : { detail: t("admin.hr.pay.error") },
      );
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    const parsed = parseDecimalInput(amount.trim(), 3);
    if (parsed === null || parsed.startsWith("-") || Number(parsed) === 0)
      found.amount = t("admin.hr.pay.invalidAmount");
    if (!paidOn) found.paid_on = t("admin.hr.form.required");
    if (parsed !== null && overpay(parsed) && !confirmOverpay) found.overpay = t("admin.hr.pay.overpay");
    setErrors(found);
    if (Object.keys(found).length > 0 || parsed === null) return;
    save.mutate(parsed);
  }

  const typedAmount = parseDecimalInput(amount.trim(), 3);
  const overOwed = typedAmount !== null && overpay(typedAmount);

  return (
    <DialogContent className="w-[min(520px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.hr.pay.title", { name: record.employee.name })}</DialogTitle>
      <DialogDescription>{t("admin.hr.pay.owed", { amount: formatMoney(record.outstanding) })}</DialogDescription>
      <form id={formId} onSubmit={submit} noValidate className="grid grid-cols-2 gap-4 max-[560px]:grid-cols-1">
        <Field label={t("admin.hr.pay.kind")} htmlFor={`${formId}-kind`} className="col-span-full">
          <Select value={kind} onValueChange={(value) => setKind(value as SalaryPaymentKindEnum)}>
            <SelectTrigger id={`${formId}-kind`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAYMENT_KINDS.map((choice) => (
                <SelectItem key={choice} value={choice}>
                  {t(`admin.hr.kind.${choice}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("admin.hr.pay.paidOn")} htmlFor={`${formId}-paid_on`} error={errors.paid_on}>
          <Input
            id={`${formId}-paid_on`}
            type="date"
            max={todayInTunis()}
            value={paidOn}
            onChange={(event) => setPaidOn(event.target.value)}
          />
        </Field>
        <Field label={t("admin.hr.pay.amount")} htmlFor={`${formId}-amount`} error={errors.amount}>
          <MoneyInput
            id={`${formId}-amount`}
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            aria-invalid={errors.amount ? true : undefined}
            autoComplete="off"
            className="num"
          />
        </Field>
        <Field label={t("admin.hr.pay.method")} htmlFor={`${formId}-method`} error={errors.method}>
          <Select value={method} onValueChange={(value) => setMethod(value as SalaryPaymentMethodEnum)}>
            <SelectTrigger id={`${formId}-method`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAYMENT_METHODS.map((choice) => (
                <SelectItem key={choice} value={choice}>
                  {t(`admin.hr.method.${choice}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("admin.hr.pay.reference")} htmlFor={`${formId}-reference`} error={errors.reference}>
          <Input
            id={`${formId}-reference`}
            value={reference}
            maxLength={50}
            onChange={(event) => setReference(event.target.value)}
            autoComplete="off"
          />
        </Field>
        {kind === "advance" && (
          <p className="col-span-full text-[0.85rem] text-ink-2">{t("admin.hr.pay.advanceHint")}</p>
        )}
        {overOwed && (
          <label className="col-span-full flex items-center gap-2 text-[0.88rem]">
            <input
              type="checkbox"
              className="size-4 accent-sea"
              checked={confirmOverpay}
              onChange={(event) => setConfirmOverpay(event.target.checked)}
            />
            {t("admin.hr.pay.overpayConfirm")}
          </label>
        )}
      </form>
      <Detail message={errors.detail ?? errors.overpay} />
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.hr.form.cancel")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {save.isPending ? t("admin.hr.form.saving") : t("admin.hr.pay.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

// ---- Adjust an approved salary, or add a prime (owner point 13, D-234) ----

/**
 * Correct an approved salary: a signed amount and a reason; the record itself never changes. With `prime`, the
 * amount is a positive prime added to what is due (owner point 13), a line of its own on the salary.
 */
export function AdjustmentDialog({
  record,
  onDone,
  prime = false,
}: {
  record: SalaryRecord;
  onDone: () => void;
  prime?: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: (value: string) =>
      prime
        ? addSalaryPrime(record.id, { amount: value, reason: reason.trim() })
        : adjustSalaryRecord(record.id, { amount: value, reason: reason.trim() }),
    onSuccess: async () => {
      toast.success(prime ? t("admin.hr.prime.recorded") : t("admin.hr.adjust.recorded"));
      await refreshHr(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(
        Object.keys(fromServer).length > 0
          ? fromServer
          : { detail: prime ? t("admin.hr.prime.error") : t("admin.hr.adjust.error") },
      );
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    const parsed = parseDecimalInput(amount.trim(), 3);
    if (parsed === null || Number(parsed) === 0 || (prime && parsed.startsWith("-")))
      found.amount = prime ? t("admin.hr.prime.invalidAmount") : t("admin.hr.adjust.invalidAmount");
    if (!reason.trim()) found.reason = t("admin.hr.form.required");
    setErrors(found);
    if (Object.keys(found).length > 0 || parsed === null) return;
    save.mutate(parsed);
  }

  return (
    <DialogContent className="w-[min(520px,calc(100vw-2rem))]">
      <DialogTitle>
        {prime
          ? t("admin.hr.prime.title", { name: record.employee.name })
          : t("admin.hr.adjust.title", { name: record.employee.name })}
      </DialogTitle>
      <DialogDescription>{prime ? t("admin.hr.prime.hint") : t("admin.hr.adjust.hint")}</DialogDescription>
      <form id={formId} onSubmit={submit} noValidate className="grid grid-cols-1 gap-4">
        <Field
          label={prime ? t("admin.hr.prime.amount") : t("admin.hr.adjust.amount")}
          htmlFor={`${formId}-amount`}
          error={errors.amount}
        >
          <MoneyInput
            id={`${formId}-amount`}
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            aria-invalid={errors.amount ? true : undefined}
            autoComplete="off"
            className="num"
          />
        </Field>
        <Field
          label={prime ? t("admin.hr.prime.reason") : t("admin.hr.adjust.reason")}
          htmlFor={`${formId}-reason`}
          error={errors.reason}
        >
          <Input
            id={`${formId}-reason`}
            value={reason}
            maxLength={200}
            onChange={(event) => setReason(event.target.value)}
            aria-invalid={errors.reason ? true : undefined}
            autoComplete="off"
          />
        </Field>
      </form>
      <Detail message={errors.detail ?? errors.status} />
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.hr.form.cancel")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {save.isPending ? t("admin.hr.form.saving") : t("admin.hr.adjust.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
