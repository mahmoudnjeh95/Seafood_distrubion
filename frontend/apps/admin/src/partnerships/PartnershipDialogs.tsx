import {
  advancePartnerCapital,
  cancelPartnership,
  createPartnership,
  type LotPartnershipDetail,
  type PaymentMethodEnum,
  updatePartnership,
  useListSuppliers,
} from "@frutti/api";
import { formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
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

import { CostSelect } from "../expenses/CostSelect";
import { PAYMENT_METHODS } from "../expenses/shared";
import { fieldErrors } from "../lib/errors";
import { refreshLotResult, typed } from "./shared";

function Detail({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
      {message}
    </p>
  );
}

type Term = "owner_capital" | "partner_capital" | "profit_rate" | "loss_rate";
const AMOUNTS: readonly Term[] = ["owner_capital", "partner_capital"];
const RATES: readonly Term[] = ["profit_rate", "loss_rate"];
const LABELS: Record<Term, "ownerCapital" | "partnerCapital" | "profitRate" | "lossRate"> = {
  owner_capital: "ownerCapital",
  partner_capital: "partnerCapital",
  profit_rate: "profitRate",
  loss_rate: "lossRate",
};

/** Put a lot in partnership, or change the terms of its open partnership before the lot's first sale. */
export function PartnershipDialog({
  batch,
  partnership,
  onDone,
}: {
  batch: {
    id: number;
    number: string;
    origin?: { supplier: string; quantity: string; unitCost: string; total: string };
  };
  partnership?: LotPartnershipDetail;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const origin = batch.origin;
  const suppliers = useListSuppliers({ status: "active" });
  const [partner, setPartner] = useState(partnership ? String(partnership.partner.id) : "");
  const [values, setValues] = useState<Record<Term, string>>({
    owner_capital: partnership ? typed(partnership.owner_capital) : "",
    partner_capital: partnership ? typed(partnership.partner_capital) : "",
    profit_rate: partnership ? typed(partnership.profit_rate) : "",
    loss_rate: partnership ? typed(partnership.loss_rate) : "",
  });
  const [notes, setNotes] = useState(partnership?.notes ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: (terms: Record<Term, string>) =>
      partnership
        ? updatePartnership(partnership.id, { partner: Number(partner), ...terms, notes: notes.trim() })
        : createPartnership({ batch: batch.id, partner: Number(partner), ...terms, notes: notes.trim() }),
    onSuccess: async () => {
      toast.success(t("admin.partnerships.form.saved"));
      await refreshLotResult(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.partnerships.form.error") });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    const parsed = {} as Record<Term, string>;
    if (!partner) found.partner = t("admin.partnerships.form.required");
    for (const field of AMOUNTS) {
      const value = parseDecimalInput(values[field].trim() || "0", 3);
      if (value === null || value.startsWith("-")) found[field] = t("admin.partnerships.form.invalidAmount");
      else parsed[field] = value;
    }
    for (const field of RATES) {
      const value = parseDecimalInput(values[field].trim(), 2);
      if (value === null || value.startsWith("-") || Number(value) > 100) {
        found[field] = t("admin.partnerships.form.invalidRate");
      } else parsed[field] = value;
    }
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    save.mutate(parsed);
  }

  const title = partnership ? "admin.partnerships.form.editTitle" : "admin.partnerships.form.createTitle";
  return (
    <DialogContent className="w-[min(560px,calc(100vw-2rem))]">
      <DialogTitle>{t(title, { number: batch.number })}</DialogTitle>
      <DialogDescription>{t("admin.partnerships.form.description")}</DialogDescription>
      {origin && (
        <p className="rounded-chip bg-sea-soft px-3 py-2 text-[0.88rem] text-ink-2">
          {t("admin.partnerships.form.origin", {
            supplier: origin.supplier,
            quantity: formatQuantity(origin.quantity),
            unitCost: formatMoney(origin.unitCost),
            total: formatMoney(origin.total),
          })}
        </p>
      )}
      <form id={formId} onSubmit={submit} noValidate className="grid grid-cols-2 gap-4 max-[560px]:grid-cols-1">
        <Field
          label={t("admin.partnerships.form.partner")}
          htmlFor={`${formId}-partner`}
          error={errors.partner}
          className="col-span-full"
        >
          <Select value={partner} onValueChange={setPartner}>
            <SelectTrigger id={`${formId}-partner`} aria-invalid={errors.partner ? true : undefined}>
              <SelectValue placeholder={t("admin.partnerships.form.choosePartner")} />
            </SelectTrigger>
            <SelectContent>
              {(suppliers.data ?? []).map((supplier) => (
                <SelectItem key={supplier.id} value={String(supplier.id)}>
                  {supplier.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {[...AMOUNTS, ...RATES].map((field) => {
          const Control = AMOUNTS.includes(field) ? MoneyInput : Input;
          return (
            <Field
              key={field}
              label={t(`admin.partnerships.form.${LABELS[field]}`)}
              htmlFor={`${formId}-${field}`}
              error={errors[field]}
            >
              <Control
                id={`${formId}-${field}`}
                inputMode="decimal"
                value={values[field]}
                onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
                aria-invalid={errors[field] ? true : undefined}
                autoComplete="off"
                className="num"
              />
            </Field>
          );
        })}
        <Field label={t("admin.partnerships.form.notes")} htmlFor={`${formId}-notes`} className="col-span-full">
          <Input id={`${formId}-notes`} value={notes} onChange={(event) => setNotes(event.target.value)} />
        </Field>
      </form>
      <Detail message={errors.detail ?? errors.batch ?? errors.non_field_errors} />
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.partnerships.form.close")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {save.isPending ? t("admin.partnerships.form.saving") : t("admin.partnerships.form.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

/** Cancel a partnership set by mistake, before the lot's first sale: the capital goes back to the partner. */
export function CancelPartnershipDialog({
  partnership,
  onDone,
}: {
  partnership: LotPartnershipDetail;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const cancel = useMutation({
    mutationFn: () => cancelPartnership(partnership.id, { reason: reason.trim() }),
    onSuccess: async () => {
      toast.success(t("admin.partnerships.cancelDialog.done"));
      await refreshLotResult(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(
        Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.partnerships.cancelDialog.error") },
      );
    },
  });

  return (
    <DialogContent className="w-[min(480px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.partnerships.cancelDialog.title")}</DialogTitle>
      <DialogDescription>{t("admin.partnerships.cancelDialog.description")}</DialogDescription>
      <form
        id={formId}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          cancel.mutate();
        }}
      >
        <Field label={t("admin.partnerships.cancelDialog.reason")} htmlFor={`${formId}-reason`} error={errors.reason}>
          <Input id={`${formId}-reason`} value={reason} onChange={(event) => setReason(event.target.value)} />
        </Field>
      </form>
      <Detail message={errors.detail} />
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.partnerships.cancelDialog.back")}</Button>
        <Button type="submit" form={formId} variant="danger" disabled={cancel.isPending}>
          {t("admin.partnerships.cancelDialog.confirm")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

/** Today as YYYY-MM-DD, in the local time zone (the value of a date input). */
const todayIso = () => new Date().toLocaleDateString("en-CA");

/** An advance paid to the partner from the capital they put in this lot. The settlement pays what is left. */
export function AdvanceDialog({ partnership, onDone }: { partnership: LotPartnershipDetail; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [amount, setAmount] = useState("");
  const [paidOn, setPaidOn] = useState(todayIso);
  const [method, setMethod] = useState<PaymentMethodEnum>("cash");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const advance = useMutation({
    mutationFn: (value: string) =>
      advancePartnerCapital(partnership.id, {
        amount: value,
        method,
        reference: reference.trim(),
        paid_on: paidOn,
        note: note.trim(),
      }),
    onSuccess: async () => {
      toast.success(t("admin.partnerships.advanceDialog.done"));
      await refreshLotResult(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(
        Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.partnerships.advanceDialog.error") },
      );
    },
  });

  return (
    <DialogContent className="w-[min(480px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.partnerships.advanceDialog.title")}</DialogTitle>
      <DialogDescription>{t("admin.partnerships.advanceDialog.description")}</DialogDescription>
      <p className="font-semibold">
        {t("admin.partnerships.advanceDialog.available", { amount: formatMoney(partnership.capital) })}
      </p>
      <form
        id={formId}
        noValidate
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          const value = parseDecimalInput(amount.trim(), 3);
          if (value === null || Number(value) <= 0) {
            setErrors({ amount: t("admin.partnerships.advanceDialog.invalidAmount") });
            return;
          }
          setErrors({});
          advance.mutate(value);
        }}
      >
        <Field label={t("admin.partnerships.advanceDialog.amount")} htmlFor={`${formId}-amount`} error={errors.amount}>
          <MoneyInput
            id={`${formId}-amount`}
            inputMode="decimal"
            className="num"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            autoComplete="off"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3 max-[720px]:grid-cols-1">
          <Field label={t("admin.partnerships.advanceDialog.date")} htmlFor={`${formId}-date`} error={errors.paid_on}>
            <Input
              id={`${formId}-date`}
              type="date"
              value={paidOn}
              onChange={(event) => setPaidOn(event.target.value)}
            />
          </Field>
          <CostSelect
            id={`${formId}-method`}
            label={t("admin.partnerships.advanceDialog.method")}
            value={method}
            onChange={(value) => setMethod(value as PaymentMethodEnum)}
            options={PAYMENT_METHODS.map((value) => ({ value, label: t(`admin.expenses.methods.${value}`) }))}
            placeholder={t("admin.partnerships.advanceDialog.choose")}
            error={errors.method}
          />
        </div>
        <Field label={t("admin.partnerships.advanceDialog.reference")} htmlFor={`${formId}-reference`}>
          <Input
            id={`${formId}-reference`}
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            autoComplete="off"
          />
        </Field>
        <Field label={t("admin.partnerships.advanceDialog.note")} htmlFor={`${formId}-note`} error={errors.note}>
          <Input id={`${formId}-note`} value={note} onChange={(event) => setNote(event.target.value)} />
        </Field>
      </form>
      <Detail message={errors.detail} />
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.partnerships.advanceDialog.back")}</Button>
        <Button type="submit" form={formId} disabled={advance.isPending}>
          {t("admin.partnerships.advanceDialog.confirm")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
