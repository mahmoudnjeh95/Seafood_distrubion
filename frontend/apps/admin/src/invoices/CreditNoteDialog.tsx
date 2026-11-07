import {
  createCreditNote,
  type CreditLineStockEnum,
  type CreditNoteKindEnum,
  type CreditNoteLineWrite,
  type InvoiceDetail,
  type RefundMethodEnum,
  useListTreasuryAccounts,
} from "@frutti/api";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { isZero } from "../lib/lines";
import { lineTotal, subtract, toThousandths } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { refreshAfterInvoice } from "./shared";

/** What one invoice line gives back: kilos or an amount, and what becomes of the kilos (D-284). */
type Entry = { quantity: string; amount: string; stock: CreditLineStockEnum | "" };

const STOCKS = ["restock", "loss", "none"] as const;
const REFUND_METHODS = ["cash", "transfer", "cheque"] as const;
// The Select needs a value for "no account chosen": the Caisse for cash, the main bank account otherwise.
const DEFAULT_ACCOUNT = "default";

const isEmpty = (entry: Entry | undefined) => !entry || (entry.quantity.trim() === "" && entry.amount.trim() === "");
const hasKilos = (entry: Entry | undefined) => {
  const quantity = parseDecimalInput(entry?.quantity.trim() ?? "", 3);
  return quantity !== null && toThousandths(quantity) > 0n;
};

/** One stock choice: three buttons, nothing chosen until the user says (returned goods are never forgotten). */
function StockChoice({
  name,
  value,
  onChange,
  error,
}: {
  name: string;
  value: CreditLineStockEnum | "";
  onChange: (value: CreditLineStockEnum) => void;
  error?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="radiogroup"
        aria-label={t("admin.invoices.creditDialog.stockOf", { name })}
        className="flex flex-wrap gap-2"
      >
        {STOCKS.map((stock) => (
          <label
            key={stock}
            title={t(`admin.invoices.creditDialog.stockHints.${stock}`)}
            className={
              "flex cursor-pointer items-center gap-2 rounded-control border px-3 py-1.5 text-[0.86rem] " +
              (value === stock ? "border-sea bg-sea-soft font-semibold text-sea" : "border-line text-ink")
            }
          >
            <input
              type="radio"
              className="size-3.5 accent-sea"
              name={`stock-${name}`}
              checked={value === stock}
              onChange={() => onChange(stock)}
            />
            {t(`admin.invoices.creditDialog.stocks.${stock}`)}
          </label>
        ))}
      </div>
      {error && (
        <p role="alert" className="text-[0.82rem] font-semibold text-bad">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * The credit note: the only way to correct an issued invoice. Whole (cancels it) or part, per line. Each line with
 * kilos says what becomes of them: back in stock, written off as a loss on its lot, or not taken back (D-284). When
 * the invoice was paid, the money given back beyond the debt left is refunded now (from a caisse or a bank account)
 * or left "À rembourser" for the treasurer.
 */
export function CreditNoteDialog({ invoice, onClose }: { invoice: InvoiceDetail; onClose: () => void }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<CreditNoteKindEnum>("full");
  const [stock, setStock] = useState<CreditLineStockEnum | "">("");
  const [reason, setReason] = useState("");
  const [entries, setEntries] = useState<Record<number, Entry>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  // Money (D-284): only asked when something was paid on the invoice.
  const paid = invoice.status === "issued" && !isZero(invoice.paid_total);
  const [refundMode, setRefundMode] = useState<"now" | "later" | "">("");
  const [method, setMethod] = useState<RefundMethodEnum>("cash");
  const [account, setAccount] = useState(DEFAULT_ACCOUNT);
  const [reference, setReference] = useState("");
  const accounts = useListTreasuryAccounts({ active_only: true }, { query: { enabled: paid } });
  const accountChoices = (accounts.data ?? []).filter((row) =>
    method === "cash" ? row.kind === "cash" || row.kind === "driver" : row.kind === "bank",
  );

  const mutation = useMutation({
    mutationFn: () => {
      const found: Record<string, string> = {};
      if (reason.trim() === "") found.reason = t("admin.invoices.creditDialog.reasonRequired");
      const lines: CreditNoteLineWrite[] = [];
      if (kind === "full" && stock === "") found.stock = t("admin.invoices.creditDialog.stockRequired");
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
          if (hasKilos(entry) && entry.stock === "") {
            found[`lines.${index}.stock`] = t("admin.invoices.creditDialog.stockRequired");
            return;
          }
          lines.push({
            invoice_line: line.id,
            quantity,
            amount,
            stock: hasKilos(entry) ? (entry.stock as CreditLineStockEnum) : "none",
          });
        });
        if (lines.length === 0 && Object.keys(found).length === 0)
          found.lines = t("admin.invoices.creditDialog.noLines");
      }
      if (paid && refundMode === "") found.refund = t("admin.invoices.creditDialog.refundRequired");
      if (Object.keys(found).length > 0) {
        setErrors(found);
        return Promise.reject(new Error("invalid"));
      }
      return createCreditNote(invoice.id, {
        kind,
        reason: reason.trim(),
        lines,
        stock: kind === "full" ? (stock as CreditLineStockEnum) : null,
        refund:
          refundMode === "now"
            ? {
                mode: "now",
                method,
                account: account === DEFAULT_ACCOUNT ? null : Number(account),
                reference: reference.trim(),
              }
            : { mode: "later" },
      });
    },
    onSuccess: async (note) => {
      const refund = note.refund;
      toast.success(
        refund
          ? t(
              refund.status === "refunded"
                ? "admin.invoices.creditDialog.doneRefunded"
                : "admin.invoices.creditDialog.doneToRefund",
              {
                number: note.number,
                amount: formatMoney(refund.amount),
              },
            )
          : t("admin.invoices.creditDialog.done", { number: note.number }),
      );
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
    setEntries((current) => ({ ...current, [id]: { quantity: "", amount: "", stock: "", ...current[id], ...patch } }));
  const lineErrors = Object.entries(errors).filter(([key]) => key.startsWith("lines") && !key.endsWith(".stock"));
  const refundErrors = Object.entries(errors).filter(([key]) => key === "refund" || key.startsWith("refund."));

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
      <DialogContent className="w-[min(760px,calc(100vw-2rem))]">
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
          <div className="flex max-h-80 flex-col gap-4 overflow-y-auto">
            {invoice.lines.map((line, index) => {
              const left = (Number(line.quantity) - Number(line.credited_quantity)).toFixed(3);
              const entry = entries[line.id];
              return (
                <fieldset key={line.id} className="grid grid-cols-2 gap-3 border-b border-line pb-3 last:border-0">
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
                      value={entry?.quantity ?? ""}
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
                      disabled={(entry?.quantity ?? "").trim() !== ""}
                      value={entry?.amount ?? ""}
                      onChange={(event) => setEntry(line.id, { amount: event.target.value, quantity: "" })}
                    />
                  </Field>
                  {hasKilos(entry) && (
                    <div className="col-span-2 flex flex-col gap-1">
                      <span className="text-[0.84rem] font-semibold">{t("admin.invoices.creditDialog.stockLine")}</span>
                      <StockChoice
                        name={line.product_name}
                        value={entry?.stock ?? ""}
                        onChange={(value) => setEntry(line.id, { stock: value })}
                        error={errors[`lines.${index}.stock`]}
                      />
                    </div>
                  )}
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

        {kind === "full" && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[0.88rem] font-semibold">{t("admin.invoices.creditDialog.stock")}</span>
            <StockChoice name={invoice.number} value={stock} onChange={setStock} error={errors.stock} />
            {stock !== "" && (
              <p className="text-[0.82rem] text-ink-2">{t(`admin.invoices.creditDialog.stockHints.${stock}`)}</p>
            )}
          </div>
        )}

        {paid && (
          <div className="flex flex-col gap-2 rounded-control border border-line p-3">
            <span className="text-[0.88rem] font-semibold">{t("admin.invoices.creditDialog.refund")}</span>
            <p className="text-[0.82rem] text-ink-2">
              {t("admin.invoices.creditDialog.refundHint", { paid: formatMoney(invoice.paid_total) })}
            </p>
            {(["now", "later"] as const).map((value) => (
              <label key={value} className="flex items-start gap-2.5 text-[0.92rem]">
                <input
                  type="radio"
                  name={`${formId}-refund`}
                  className="mt-1 size-4 accent-sea"
                  checked={refundMode === value}
                  onChange={() => setRefundMode(value)}
                />
                <span>
                  <span className="font-semibold">{t(`admin.invoices.creditDialog.refundModes.${value}`)}</span>
                  <span className="block text-[0.82rem] text-ink-2">
                    {t(`admin.invoices.creditDialog.refundModeHints.${value}`)}
                  </span>
                </span>
              </label>
            ))}
            {refundMode === "now" && (
              <div className="grid grid-cols-3 gap-3 max-[640px]:grid-cols-1">
                <Field label={t("admin.refunds.method")} htmlFor={`${formId}-method`}>
                  <Select
                    value={method}
                    onValueChange={(value) => {
                      setMethod(value as RefundMethodEnum);
                      setAccount(DEFAULT_ACCOUNT);
                    }}
                  >
                    <SelectTrigger id={`${formId}-method`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {REFUND_METHODS.map((value) => (
                        <SelectItem key={value} value={value}>
                          {t(`admin.refunds.methods.${value}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label={t("admin.refunds.account")} htmlFor={`${formId}-account`}>
                  <Select value={account} onValueChange={setAccount}>
                    <SelectTrigger id={`${formId}-account`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={DEFAULT_ACCOUNT}>
                        {t(method === "cash" ? "admin.refunds.defaultCash" : "admin.refunds.defaultBank")}
                      </SelectItem>
                      {accountChoices.map((row) => (
                        <SelectItem key={row.id} value={String(row.id)}>
                          {row.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label={t("admin.refunds.reference")} htmlFor={`${formId}-reference`}>
                  <Input
                    id={`${formId}-reference`}
                    value={reference}
                    maxLength={50}
                    onChange={(event) => setReference(event.target.value)}
                  />
                </Field>
              </div>
            )}
            {refundErrors.map(([key, message]) => (
              <p key={key} role="alert" className="text-[0.82rem] font-semibold text-bad">
                {message}
              </p>
            ))}
          </div>
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
