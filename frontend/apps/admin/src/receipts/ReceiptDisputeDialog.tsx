import { disputeReceipt, type Receipt, resolveReceiptDispute } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, DialogContent, DialogDescription, DialogFooter, DialogTitle, Field, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { refreshAfterReceipt } from "./shared";

/** Contest a receipt with its supplier, or lift its open dispute (D-285). Contesting asks for the reason ("motif de
 * contestation"), lifting for how it was settled; while contested no supplier invoice takes the receipt. */
export function ReceiptDisputeDialog({
  receipt,
  mode,
  onDone,
}: {
  receipt: Receipt;
  mode: "dispute" | "resolve";
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const key = mode === "dispute" ? "reason" : "resolution";

  const save = useMutation({
    mutationFn: (typed: string) =>
      mode === "dispute"
        ? disputeReceipt(receipt.id, { reason: typed })
        : resolveReceiptDispute(receipt.id, { resolution: typed }),
    onSuccess: async () => {
      toast.success(t(`admin.receipts.dispute.${mode}Saved`, { number: receipt.number }));
      await refreshAfterReceipt(queryClient);
      onDone();
    },
    onError: (failure) => {
      const errors = fieldErrors(failure);
      setError(errors[key] ?? errors.detail ?? errors.non_field_errors ?? t("admin.receipts.dispute.error"));
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (text.trim() === "") {
      setError(t(`admin.receipts.dispute.${key}Required`));
      return;
    }
    setError(null);
    save.mutate(text.trim());
  }

  return (
    <DialogContent>
      <DialogTitle>{t(`admin.receipts.dispute.${mode}Title`, { number: receipt.number })}</DialogTitle>
      <DialogDescription>{t(`admin.receipts.dispute.${mode}Hint`)}</DialogDescription>
      <form id={formId} onSubmit={submit} className="flex flex-col gap-3">
        <Field label={t(`admin.receipts.dispute.${key}`)} htmlFor={`${formId}-text`} error={error ?? undefined}>
          <textarea
            id={`${formId}-text`}
            rows={3}
            value={text}
            onChange={(event) => setText(event.target.value)}
            aria-invalid={error ? true : undefined}
            className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
          />
        </Field>
      </form>
      <DialogFooter className="items-center">
        <Button onClick={onDone}>{t("admin.receipts.dispute.cancel")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {t(`admin.receipts.dispute.${mode}Save`)}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
