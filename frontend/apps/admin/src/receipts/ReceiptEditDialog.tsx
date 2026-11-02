import { type Receipt, type ReceiptRevisionWrite, reviseReceipt } from "@frutti/api";
import { parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Input,
  MoneyInput,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { refreshAfterReceipt } from "./shared";

type Draft = { invoiced: string; accepted: string; cost: string; useBy: string };
type Errors = Record<string, string>;

const weightOf = (typed: string) => {
  const parsed = parseDecimalInput(typed.trim(), 3);
  return parsed !== null && Number(parsed) > 0 ? parsed : null;
};

const moneyOf = (typed: string) => {
  const parsed = parseDecimalInput(typed.trim(), 3);
  return parsed !== null && !parsed.startsWith("-") ? parsed : null;
};

/** Change a receipt after it was saved (D-269): its header and every line's weights, cost and use-by date, with a
 * reason. A weight that goes down leaves the stock by an adjustment; the server refuses what already left the lot. */
export function ReceiptEditDialog({ receipt, onDone }: { receipt: Receipt; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [supplierReference, setSupplierReference] = useState(receipt.supplier_reference);
  const [notes, setNotes] = useState(receipt.notes);
  const [withVat, setWithVat] = useState(receipt.with_vat);
  const [drafts, setDrafts] = useState<Draft[]>(() =>
    receipt.lines.map((line) => ({
      invoiced: line.invoiced_quantity,
      accepted: line.accepted_quantity,
      cost: line.unit_cost,
      useBy: line.batch.use_by ?? "",
    })),
  );
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Errors>({});

  const setDraft = (index: number, field: keyof Draft, value: string) =>
    setDrafts((rows) => rows.map((row, position) => (position === index ? { ...row, [field]: value } : row)));

  const save = useMutation({
    mutationFn: (body: ReceiptRevisionWrite) => reviseReceipt(receipt.id, body),
    onSuccess: async () => {
      toast.success(t("admin.receipts.edit.saved", { number: receipt.number }));
      await refreshAfterReceipt(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.receipts.edit.error") });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!reason.trim()) found.reason = t("admin.receipts.edit.reasonRequired");
    const lines: ReceiptRevisionWrite["lines"] = [];
    drafts.forEach((row, index) => {
      const invoiced = weightOf(row.invoiced);
      const accepted = weightOf(row.accepted);
      const cost = moneyOf(row.cost);
      if (invoiced === null) found[`lines.${index}.invoiced_quantity`] = t("admin.receipts.edit.weight");
      if (accepted === null) found[`lines.${index}.accepted_quantity`] = t("admin.receipts.edit.weight");
      if (cost === null) found[`lines.${index}.unit_cost`] = t("admin.receipts.edit.money");
      lines.push({
        id: receipt.lines[index].id,
        invoiced_quantity: invoiced ?? "",
        accepted_quantity: accepted ?? "",
        unit_cost: cost ?? "",
        use_by: row.useBy || null,
      });
    });
    setErrors(found);
    if (Object.keys(found).length === 0) {
      save.mutate({
        revision: receipt.revision,
        reason: reason.trim(),
        supplier_reference: supplierReference.trim(),
        notes: notes.trim(),
        with_vat: withVat,
        lines,
      });
    }
  }

  // Errors that are not on one input: the version, the lines, the VAT flag, or the refusal of the whole change.
  const general =
    errors.detail ?? errors.revision ?? errors.lines ?? errors.with_vat ?? errors.non_field_errors ?? errors.reason;
  const cellError = (key: string) =>
    errors[key] ? (
      <p role="alert" className="px-2.5 pb-1.5 text-[0.75rem] font-semibold text-bad">
        {errors[key]}
      </p>
    ) : null;
  const cellClass = "w-full bg-transparent px-2.5 py-1.5 text-end";

  return (
    <DialogContent>
      <DialogTitle>{t("admin.receipts.edit.title", { number: receipt.number })}</DialogTitle>
      <DialogDescription>{t("admin.receipts.edit.hint")}</DialogDescription>
      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("admin.receipts.edit.supplierReference")} htmlFor={`${formId}-reference`}>
            <Input
              id={`${formId}-reference`}
              value={supplierReference}
              maxLength={50}
              onChange={(event) => setSupplierReference(event.target.value)}
              autoComplete="off"
            />
          </Field>
          <label className="flex items-center gap-2.5 self-end pb-2.5 font-semibold">
            <input
              type="checkbox"
              className="size-4 accent-sea"
              checked={withVat}
              onChange={(event) => setWithVat(event.target.checked)}
            />
            {t("admin.receipts.edit.withVat")}
          </label>
        </div>
        <Field label={t("admin.receipts.edit.notes")} htmlFor={`${formId}-notes`}>
          <Input
            id={`${formId}-notes`}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            autoComplete="off"
          />
        </Field>

        <div className="overflow-x-auto">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.receipts.edit.product")}</Th>
                <Th numeric>{t("admin.receipts.edit.invoiced")}</Th>
                <Th numeric>{t("admin.receipts.edit.accepted")}</Th>
                <Th numeric>{t("admin.receipts.edit.cost")}</Th>
                <Th>{t("admin.receipts.edit.useBy")}</Th>
              </tr>
            </thead>
            <tbody>
              {receipt.lines.map((line, index) => (
                <tr key={line.id}>
                  <Td>
                    <span className="font-semibold">{line.product.name}</span>
                    <div className="num text-[0.8rem] text-ink-2">{line.batch.number}</div>
                  </Td>
                  <Td className="p-0">
                    <input
                      aria-label={t("admin.receipts.edit.invoiced")}
                      inputMode="decimal"
                      className={`num ${cellClass}`}
                      value={drafts[index].invoiced}
                      onChange={(event) => setDraft(index, "invoiced", event.target.value)}
                      aria-invalid={errors[`lines.${index}.invoiced_quantity`] ? true : undefined}
                    />
                    {cellError(`lines.${index}.invoiced_quantity`)}
                  </Td>
                  <Td className="p-0">
                    <input
                      aria-label={t("admin.receipts.edit.accepted")}
                      inputMode="decimal"
                      className={`num ${cellClass}`}
                      value={drafts[index].accepted}
                      onChange={(event) => setDraft(index, "accepted", event.target.value)}
                      aria-invalid={errors[`lines.${index}.accepted_quantity`] ? true : undefined}
                    />
                    {cellError(`lines.${index}.accepted_quantity`)}
                  </Td>
                  <Td className="p-0">
                    <MoneyInput
                      aria-label={t("admin.receipts.edit.cost")}
                      className={`num ${cellClass}`}
                      value={drafts[index].cost}
                      onChange={(event) => setDraft(index, "cost", event.target.value)}
                      aria-invalid={errors[`lines.${index}.unit_cost`] ? true : undefined}
                    />
                    {cellError(`lines.${index}.unit_cost`)}
                  </Td>
                  <Td className="p-0">
                    <input
                      type="date"
                      aria-label={t("admin.receipts.edit.useBy")}
                      className="num w-full bg-transparent px-2.5 py-1.5"
                      value={drafts[index].useBy}
                      onChange={(event) => setDraft(index, "useBy", event.target.value)}
                      aria-invalid={errors[`lines.${index}.use_by`] ? true : undefined}
                    />
                    {cellError(`lines.${index}.use_by`)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>

        <Field label={t("admin.receipts.edit.reason")} htmlFor={`${formId}-reason`} error={errors.reason}>
          <Input
            id={`${formId}-reason`}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            aria-invalid={errors.reason ? true : undefined}
            autoComplete="off"
          />
        </Field>
      </form>
      {general && (
        <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
          {general}
        </p>
      )}
      <DialogFooter className="items-center">
        <Button onClick={onDone}>{t("admin.receipts.edit.cancel")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {t("admin.receipts.edit.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
