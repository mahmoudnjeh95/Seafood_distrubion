import { useTranslation } from "@frutti/i18n";
import { Button, Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@frutti/ui";
import type { ReactNode } from "react";

/** The last look before a règlement is recorded (D-179): who, the total, how it is paid and where it goes. Shown
 * once the form is checked; "Confirmer" sends it. */
export function ConfirmPaymentDialog({
  open,
  title,
  rows,
  means,
  pending,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: ReactNode;
  rows: [ReactNode, ReactNode][];
  /** One short line per means ("Chèque 4401 · BIAT · 30/11/2026 — 1 000,000 DT"). */
  means: ReactNode[];
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription asChild>
          <div className="flex flex-col gap-3">
            <dl className="space-y-1">
              {rows.map(([label, value], index) => (
                <div key={index} className="flex items-baseline justify-between gap-3">
                  <dt>{label}</dt>
                  <dd className="num text-lg font-bold text-ink">{value}</dd>
                </div>
              ))}
            </dl>
            <ul className="flex flex-col gap-1 border-t border-line pt-2 text-[0.88rem]">
              {means.map((line, index) => (
                <li key={index} className="num">
                  {line}
                </li>
              ))}
            </ul>
          </div>
        </DialogDescription>
        <DialogFooter className="grid grid-cols-2">
          <DialogClose asChild>
            <Button size="lg">{t("common.cancel")}</Button>
          </DialogClose>
          <Button size="lg" variant="primary" disabled={pending} onClick={onConfirm}>
            {pending ? t("admin.treasury.form.saving") : t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
