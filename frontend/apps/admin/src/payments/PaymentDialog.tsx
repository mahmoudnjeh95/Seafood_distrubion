import { createCustomerPayment, type CustomerPaymentMethodEnum, useListBanks } from "@frutti/api";
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

import { fieldErrors } from "../lib/errors";
import { CUSTOMER_PAYMENT_METHODS, isInstrumentMethod, lineErrors, refreshAfterPayment, todayInput } from "./shared";

/** Register money received from a customer, by one means: it settles their oldest open sales first; the rest is
 * credit. A cheque or a traite asks its number, bank and échéance (D-197). */
export function PaymentDialog({
  customer,
  owed,
  onClose,
}: {
  customer: { id: number; name: string };
  /** What the customer owes now, proposed as the amount. */
  owed?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const [amount, setAmount] = useState(owed && Number(owed) > 0 ? owed.replace(".", ",") : "");
  const [method, setMethod] = useState<CustomerPaymentMethodEnum>("cash");
  const [receivedOn, setReceivedOn] = useState(todayInput());
  const [reference, setReference] = useState("");
  const [bank, setBank] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [drawer, setDrawer] = useState("");
  const banks = useListBanks();
  const paper = isInstrumentMethod(method);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const mutation = useMutation({
    mutationFn: () => {
      const value = parseDecimalInput(amount, 3);
      if (value === null || Number(value) <= 0) {
        setErrors({ amount: t("admin.payments.dialog.amountError") });
        return Promise.reject(new Error("invalid"));
      }
      return createCustomerPayment({
        customer: customer.id,
        received_on: receivedOn || null,
        lines: [
          paper
            ? {
                method,
                amount: value,
                number: reference.trim(),
                bank: bank ? Number(bank) : null,
                due_on: dueOn || null,
                drawer: drawer.trim(),
              }
            : { method, amount: value, reference: reference.trim() },
        ],
      });
    },
    onSuccess: async (payment) => {
      toast.success(t("admin.payments.dialog.done", { number: payment.number }));
      await refreshAfterPayment(queryClient);
      onClose();
    },
    onError: (failure) => {
      const fromServer = lineErrors(fieldErrors(failure), 0);
      if (Object.keys(fromServer).length > 0) setErrors(fromServer);
      else if (!(failure instanceof Error && failure.message === "invalid"))
        toast.error(t("admin.payments.dialog.error"));
    },
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{t("admin.payments.dialog.title", { name: customer.name })}</DialogTitle>
        <DialogDescription>
          {owed !== undefined
            ? t("admin.payments.dialog.bodyOwed", { amount: formatMoney(owed) })
            : t("admin.payments.dialog.body")}
        </DialogDescription>
        <div className="grid grid-cols-2 gap-3 max-[520px]:grid-cols-1">
          <Field label={t("admin.payments.dialog.amount")} htmlFor={`${formId}-amount`} error={errors.amount}>
            <MoneyInput
              id={`${formId}-amount`}
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              aria-invalid={errors.amount ? true : undefined}
              autoComplete="off"
            />
          </Field>
          <Field label={t("admin.payments.dialog.method")} htmlFor={`${formId}-method`} error={errors.method}>
            <Select value={method} onValueChange={(value) => setMethod(value as CustomerPaymentMethodEnum)}>
              <SelectTrigger id={`${formId}-method`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CUSTOMER_PAYMENT_METHODS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {t(`admin.sales.methods.${value}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("admin.payments.dialog.receivedOn")} htmlFor={`${formId}-day`} error={errors.received_on}>
            <Input
              id={`${formId}-day`}
              type="date"
              value={receivedOn}
              onChange={(event) => setReceivedOn(event.target.value)}
            />
          </Field>
          <Field
            label={paper ? t("admin.payments.dialog.number") : t("admin.payments.dialog.reference")}
            htmlFor={`${formId}-ref`}
            error={paper ? errors.number : errors.reference}
          >
            <Input
              id={`${formId}-ref`}
              value={reference}
              maxLength={50}
              onChange={(event) => setReference(event.target.value)}
              autoComplete="off"
            />
          </Field>
          {paper && (
            <>
              <Field label={t("admin.payments.dialog.bank")} htmlFor={`${formId}-bank`} error={errors.bank}>
                <Select value={bank} onValueChange={setBank}>
                  <SelectTrigger id={`${formId}-bank`}>
                    <SelectValue placeholder={t("admin.payments.dialog.bankPlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(banks.data ?? []).map((row) => (
                      <SelectItem key={row.id} value={String(row.id)}>
                        {row.code} · {row.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label={t("admin.payments.dialog.dueOn")} htmlFor={`${formId}-due`} error={errors.due_on}>
                <Input
                  id={`${formId}-due`}
                  type="date"
                  value={dueOn}
                  onChange={(event) => setDueOn(event.target.value)}
                />
              </Field>
              <Field
                label={t("admin.payments.dialog.drawer")}
                htmlFor={`${formId}-drawer`}
                error={errors.drawer}
                className="col-span-2 max-[520px]:col-span-1"
              >
                <Input
                  id={`${formId}-drawer`}
                  value={drawer}
                  maxLength={150}
                  placeholder={customer.name}
                  onChange={(event) => setDrawer(event.target.value)}
                  autoComplete="off"
                />
              </Field>
            </>
          )}
        </div>
        {errors.customer && (
          <p role="alert" className="text-[0.85rem] text-bad">
            {errors.customer}
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("admin.payments.dialog.cancel")}
          </Button>
          <Button variant="primary" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
            {mutation.isPending ? t("admin.payments.dialog.saving") : t("admin.payments.dialog.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
