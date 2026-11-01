import { createCreditNote, type CreditNoteKindEnum, type CreditNoteStockEnum, type InvoiceDetail } from "@frutti/api";
import { formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
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
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { lineTotal, subtract, toThousandths } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { refreshAfterInvoice } from "./shared";

type Entry = { quantity: string; amount: string };

const isEmpty = (entry: Entry | undefined) => !entry || (entry.quantity.trim() === "" && entry.amount.trim() === "");

/** The credit note: the only way to correct an issued invoice. Whole (cancels it) or part, per line. */
export function CreditNoteDialog({ invoice, onClose }: { invoice: InvoiceDetail; onClose: () => void }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<CreditNoteKindEnum>("full");
  const [stock, setStock] = useState<CreditNoteStockEnum>("none");
  const [reason, setReason] = useState("");
  const [entries, setEntries] = useState<Record<number, Entry>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  const mutation = useMutation({
    mutationFn: () => {
      const found: Record<string, string> = {};
      if (reason.trim() === "") found.reason = t("admin.invoices.creditDialog.reasonRequired");
      const lines: { invoice_line: number; quantity: string | null; amount: string | null }[] = [];
      if (kind === "partial") {
        invoice.lines.forEach((line, index) => {
          const entry = entries[line.id];
          if (isEmpty(entry) || !entry) return;
          const hasQuantity = entry.quantity.trim() !== "";
          const quantity = hasQuantity ? parseDecimalInput(entry.quantity, 3) : null;
          // With kilos given, the server works out the amount itself (same proportion, exact rounding);
          // the field only previews it. Without kilos, the typed amount is the correction itself.
          const amount = hasQuantity ? null : entry.amount.trim() === "" ? null : parseDecimalInput(entry.amount, 3);
          if ((hasQuantity && quantity === null) || (!hasQuantity && entry.amount.trim() !== "" && amount === null)) {
            found[`lines.${index}`] = t("admin.invoices.creditDialog.numberError");
            return;
          }
          lines.push({ invoice_line: line.id, quantity, amount });
        });
        if (lines.length === 0 && Object.keys(found).length === 0)
          found.lines = t("admin.invoices.creditDialog.noLines");
      }
      if (Object.keys(found).length > 0) {
        setErrors(found);
        return Promise.reject(new Error("invalid"));
      }
      return createCreditNote(invoice.id, { kind, reason: reason.trim(), lines, stock });
    },
    onSuccess: async (note) => {
      toast.success(t("admin.invoices.creditDialog.done", { number: note.number }));
      await refreshAfterInvoice(queryClient);
      onClose();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      if (Object.keys(fromServer).length > 0) setErrors(fromServer);
      else if (!(failure instanceof Error && failure.message === "invalid"))
        toast.error(t("admin.invoices.detail.actionError"));
    },
  });

  const setEntry = (id: number, patch: Partial<Entry>) =>
    setEntries((current) => ({ ...current, [id]: { quantity: "", amount: "", ...current[id], ...patch } }));
  const lineErrors = Object.entries(errors).filter(([key]) => key.startsWith("lines"));

  /** What giving back `quantityText` kg of `line` is worth, at the price it was sold to this customer. */
  const previewAmount = (line: InvoiceDetail["lines"][number], quantityText: string): string => {
    const quantity = parseDecimalInput(quantityText, 3);
    if (quantity === null) return "";
    const exclLeft = subtract(line.amount_excl_tax, line.credited_amount_excl_tax);
    const amount = lineTotal(quantity, line.unit_price_excl_tax);
    return toThousandths(amount) > toThousandths(exclLeft) ? exclLeft : amount;
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{t("admin.invoices.creditDialog.title", { number: invoice.number })}</DialogTitle>
        <DialogDescription>{t("admin.invoices.creditDialog.body")}</DialogDescription>

        <div role="group" aria-label={t("admin.invoices.creditDialog.kind")} className="flex flex-col gap-2">
          {(["full", "partial"] as const).map((value) => (
            <label key={value} className="flex items-start gap-2.5 text-[0.92rem]">
              <input
                type="radio"
                name={`${formId}-kind`}
                className="mt-1 size-4 accent-sea"
                checked={kind === value}
                onChange={() => setKind(value)}
              />
              <span>
                <span className="font-semibold">{t(`admin.invoices.creditDialog.kinds.${value}`)}</span>
                <span className="block text-[0.82rem] text-ink-2">
                  {t(`admin.invoices.creditDialog.kindHints.${value}`, {
                    amount: formatMoney(invoice.remaining_to_pay),
                  })}
                </span>
              </span>
            </label>
          ))}
        </div>

        {kind === "partial" && (
          <div className="flex max-h-72 flex-col gap-3 overflow-y-auto">
            {invoice.lines.map((line) => {
              const left = (Number(line.quantity) - Number(line.credited_quantity)).toFixed(3);
              return (
                <fieldset key={line.id} className="grid grid-cols-2 gap-3">
                  <legend className="mb-1 text-[0.88rem] font-semibold">
                    {line.product_name}
                    <span className="num ms-2 font-normal text-ink-2">
                      {t("admin.invoices.creditDialog.left", { quantity: formatQuantity(left) })}
                    </span>
                  </legend>
                  <Field
                    label={t("admin.invoices.creditDialog.quantity", { name: line.product_name })}
                    htmlFor={`${formId}-q-${line.id}`}
                  >
                    <Input
                      id={`${formId}-q-${line.id}`}
                      inputMode="decimal"
                      value={entries[line.id]?.quantity ?? ""}
                      onChange={(event) => {
                        const quantity = event.target.value;
                        setEntry(line.id, { quantity, amount: previewAmount(line, quantity) });
                      }}
                    />
                  </Field>
                  <Field
                    label={t("admin.invoices.creditDialog.amount", { name: line.product_name })}
                    htmlFor={`${formId}-a-${line.id}`}
                  >
                    <MoneyInput
                      id={`${formId}-a-${line.id}`}
                      inputMode="decimal"
                      disabled={(entries[line.id]?.quantity ?? "").trim() !== ""}
                      value={entries[line.id]?.amount ?? ""}
                      onChange={(event) => setEntry(line.id, { amount: event.target.value, quantity: "" })}
                    />
                  </Field>
                </fieldset>
              );
            })}
          </div>
        )}
        {lineErrors.map(([key, message]) => (
          <p key={key} role="alert" className="text-[0.82rem] font-semibold text-bad">
            {message}
          </p>
        ))}

        <div role="group" aria-label={t("admin.invoices.creditDialog.stock")} className="flex flex-col gap-2">
          <span className="text-[0.88rem] font-semibold">{t("admin.invoices.creditDialog.stock")}</span>
          {(["none", "restock", "loss"] as const).map((value) => (
            <label key={value} className="flex items-start gap-2.5 text-[0.92rem]">
              <input
                type="radio"
                name={`${formId}-stock`}
                className="mt-1 size-4 accent-sea"
                checked={stock === value}
                onChange={() => setStock(value)}
              />
              <span>
                <span className="font-semibold">{t(`admin.invoices.creditDialog.stocks.${value}`)}</span>
                <span className="block text-[0.82rem] text-ink-2">
                  {t(`admin.invoices.creditDialog.stockHints.${value}`)}
                </span>
              </span>
            </label>
          ))}
        </div>
        {errors.stock && (
          <p role="alert" className="text-[0.82rem] font-semibold text-bad">
            {errors.stock}
          </p>
        )}

        <Field label={t("admin.invoices.creditDialog.reason")} htmlFor={`${formId}-reason`} error={errors.reason}>
          <Input
            id={`${formId}-reason`}
            value={reason}
            maxLength={255}
            onChange={(event) => setReason(event.target.value)}
            aria-invalid={errors.reason ? true : undefined}
          />
        </Field>

        <DialogFooter>
          <Button onClick={onClose}>{t("admin.invoices.detail.keep")}</Button>
          <Button variant="danger" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
            {t("admin.invoices.creditDialog.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
