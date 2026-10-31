import { type PaymentMethodEnum, type PlanLineWrite, type SettlementRow, setSupplierInvoicePlan } from "@frutti/api";
import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Dialog,
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
import { useId, useState } from "react";

import { subtract, sum } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { todayInTunis } from "../receipts/shared";
import { asTyped } from "./allocation";
import { refreshPurchasing } from "./shared";

const METHODS: readonly PaymentMethodEnum[] = ["cash", "cheque", "transfer", "bill", "other"];

type Draft = {
  key: number;
  amount: string;
  method: PaymentMethodEnum | "";
  plannedOn: string;
  reference: string;
  cashOn: string;
};

let nextKey = 1;
const blank = (amount = ""): Draft => ({
  key: nextKey++,
  amount,
  method: "",
  plannedOn: todayInTunis(),
  reference: "",
  cashOn: "",
});

/** "Définir le règlement" (D-192): split what is left to pay on an invoice into planned lines. A plan is not a payment. */
export function PlanDialog({ row, onClose }: { row: SettlementRow; onClose: () => void }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  // What can be planned: the total minus what is paid (the open lines are replaced by the new plan).
  const remainder = subtract(row.total, row.paid);
  const [drafts, setDrafts] = useState<Draft[]>(() => {
    const open = row.plan_lines.filter((line) => line.status === "open");
    if (open.length === 0) return [blank(asTyped(remainder))];
    return open.map((line) => ({
      key: nextKey++,
      amount: asTyped(line.amount),
      method: line.method,
      plannedOn: line.planned_on,
      reference: line.reference,
      cashOn: line.cash_on ?? "",
    }));
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const parsed = drafts.map((draft) => parseDecimalInput(draft.amount.trim(), 3));
  const planned = sum(parsed.filter((value): value is string => value !== null && !value.startsWith("-")));
  const left = subtract(remainder, planned);
  const over = left.startsWith("-");

  const update = (key: number, patch: Partial<Draft>) =>
    setDrafts((current) => current.map((draft) => (draft.key === key ? { ...draft, ...patch } : draft)));

  const save = useMutation({
    mutationFn: (lines: PlanLineWrite[]) => setSupplierInvoicePlan(row.invoice_id, { lines }),
    onSuccess: async () => {
      toast.success(t("admin.supplierSettlements.dialog.saved"));
      await refreshPurchasing(queryClient);
      onClose();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(
        Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.supplierSettlements.dialog.error") },
      );
    },
  });

  function submit() {
    const found: Record<string, string> = {};
    const lines: PlanLineWrite[] = [];
    drafts.forEach((draft, index) => {
      const amount = parsed[index];
      if (amount === null || amount === undefined || amount.startsWith("-") || Number(amount) <= 0)
        found[`lines.${index}.amount`] = t("admin.supplierSettlements.dialog.amountError");
      if (!draft.method) found[`lines.${index}.method`] = t("admin.supplierSettlements.dialog.required");
      if (!draft.plannedOn) found[`lines.${index}.planned_on`] = t("admin.supplierSettlements.dialog.required");
      const postDated = draft.method === "cheque" || draft.method === "bill";
      if (amount && draft.method && draft.plannedOn)
        lines.push({
          amount,
          method: draft.method,
          planned_on: draft.plannedOn,
          reference: draft.reference.trim(),
          cash_on: postDated && draft.cashOn ? draft.cashOn : null,
        });
    });
    if (over) found.lines = t("admin.supplierSettlements.dialog.over");
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate(lines);
  }

  const id = (name: string) => `${formId}-${name}`;
  const lineError = (index: number, field: string) => errors[`lines.${index}.${field}`];

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="w-[min(720px,calc(100vw-2rem))]">
        <DialogTitle>{t("admin.supplierSettlements.dialog.title", { number: row.number })}</DialogTitle>
        <DialogDescription>
          {t("admin.supplierSettlements.dialog.body", {
            supplier: row.supplier.name,
            total: formatMoney(row.total),
            paid: formatMoney(row.paid),
          })}
        </DialogDescription>

        {drafts.map((draft, index) => {
          const postDated = draft.method === "cheque" || draft.method === "bill";
          return (
            <fieldset
              key={draft.key}
              className="grid grid-cols-2 gap-3 rounded-control border border-line p-3 max-[520px]:grid-cols-1"
            >
              <legend className="px-1 text-[0.8rem] font-semibold text-ink-2">
                {t("admin.supplierSettlements.dialog.line", { n: index + 1 })}
              </legend>
              <Field
                label={t("admin.supplierSettlements.dialog.method")}
                htmlFor={id(`m${draft.key}`)}
                error={lineError(index, "method")}
              >
                <Select
                  value={draft.method}
                  onValueChange={(value) => update(draft.key, { method: value as PaymentMethodEnum })}
                >
                  <SelectTrigger id={id(`m${draft.key}`)} aria-invalid={lineError(index, "method") ? true : undefined}>
                    <SelectValue placeholder={t("admin.supplierSettlements.dialog.choose")} />
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
                label={t("admin.supplierSettlements.dialog.amount")}
                htmlFor={id(`a${draft.key}`)}
                error={lineError(index, "amount")}
              >
                <MoneyInput
                  id={id(`a${draft.key}`)}
                  inputMode="decimal"
                  value={draft.amount}
                  onChange={(event) => update(draft.key, { amount: event.target.value })}
                  aria-invalid={lineError(index, "amount") ? true : undefined}
                  autoComplete="off"
                  className="num"
                />
              </Field>
              <Field
                label={t("admin.supplierSettlements.dialog.plannedOn")}
                htmlFor={id(`d${draft.key}`)}
                error={lineError(index, "planned_on")}
              >
                <Input
                  id={id(`d${draft.key}`)}
                  type="date"
                  value={draft.plannedOn}
                  onChange={(event) => update(draft.key, { plannedOn: event.target.value })}
                  aria-invalid={lineError(index, "planned_on") ? true : undefined}
                />
              </Field>
              <Field
                label={t("admin.supplierSettlements.dialog.reference")}
                htmlFor={id(`r${draft.key}`)}
                error={lineError(index, "reference")}
              >
                <Input
                  id={id(`r${draft.key}`)}
                  value={draft.reference}
                  maxLength={50}
                  onChange={(event) => update(draft.key, { reference: event.target.value })}
                  autoComplete="off"
                />
              </Field>
              {postDated && (
                <Field
                  label={t("admin.supplierSettlements.dialog.cashOn")}
                  htmlFor={id(`c${draft.key}`)}
                  error={lineError(index, "cash_on")}
                >
                  <Input
                    id={id(`c${draft.key}`)}
                    type="date"
                    min={draft.plannedOn}
                    value={draft.cashOn}
                    onChange={(event) => update(draft.key, { cashOn: event.target.value })}
                    aria-invalid={lineError(index, "cash_on") ? true : undefined}
                  />
                </Field>
              )}
              {drafts.length > 1 && (
                <div className="col-span-full text-end">
                  <Button
                    variant="ghost"
                    onClick={() => setDrafts((current) => current.filter((one) => one.key !== draft.key))}
                  >
                    {t("admin.supplierSettlements.dialog.removeLine")}
                  </Button>
                </div>
              )}
            </fieldset>
          );
        })}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => setDrafts((current) => [...current, blank(over || Number(left) === 0 ? "" : asTyped(left))])}
          >
            {t("admin.supplierSettlements.dialog.addLine")}
          </Button>
          <dl className="ms-auto flex flex-wrap gap-x-6 gap-y-1">
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">
                {t("admin.supplierSettlements.dialog.toPlan")}
              </dt>
              <dd className="num font-bold">{formatMoney(remainder)}</dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.supplierSettlements.dialog.left")}</dt>
              <dd className={over ? "num font-bold text-bad" : "num font-bold"}>{formatMoney(left)}</dd>
            </div>
          </dl>
        </div>
        {(errors.lines || over) && (
          <p role="alert" className="text-[0.85rem] font-semibold text-bad">
            {errors.lines ?? t("admin.supplierSettlements.dialog.over")}
          </p>
        )}
        {(errors.invoice || errors.detail) && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.invoice ?? errors.detail}
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("admin.supplierSettlements.dialog.cancel")}
          </Button>
          <Button variant="primary" disabled={save.isPending} onClick={submit}>
            {save.isPending ? t("admin.supplierSettlements.dialog.saving") : t("admin.supplierSettlements.dialog.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
