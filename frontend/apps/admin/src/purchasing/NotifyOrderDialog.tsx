import { notifyPaymentOrder, useListNoticeRecipients } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useState } from "react";

import { fieldErrors } from "../lib/errors";

/** "Notifier" on a payment order (D-255): choose who in the office is told; they see it in their bell. */
export function NotifyOrderDialog({ lineId, onClose }: { lineId: number; onClose: () => void }) {
  const { t } = useTranslation();
  const people = useListNoticeRecipients();
  const [recipient, setRecipient] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function send() {
    setPending(true);
    setError("");
    try {
      await notifyPaymentOrder(lineId, { recipient: Number(recipient) });
      toast.success(t("admin.supplierSettlements.notify.sent"));
      onClose();
    } catch (failure) {
      setError(fieldErrors(failure).recipient ?? t("admin.supplierSettlements.notify.error"));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{t("admin.supplierSettlements.notify.title")}</DialogTitle>
        <DialogDescription>{t("admin.supplierSettlements.notify.body")}</DialogDescription>
        <Field label={t("admin.supplierSettlements.notify.who")} htmlFor="notify-who" error={error}>
          <Select value={recipient} onValueChange={setRecipient}>
            <SelectTrigger id="notify-who">
              <SelectValue placeholder={t("admin.supplierSettlements.notify.choose")} />
            </SelectTrigger>
            <SelectContent>
              {(people.data ?? []).map((one) => (
                <SelectItem key={one.id} value={String(one.id)}>
                  {one.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" disabled={!recipient || pending} onClick={() => void send()}>
            {t("admin.supplierSettlements.notify.send")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
