import { deliverSale, issueSale, notDeliveredSale, type SaleDetail } from "@frutti/api";
import { formatQuantity, useTranslation } from "@frutti/i18n";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Icon,
  Input,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fieldErrors } from "../lib/errors";
import { refreshAfterSale } from "./shared";

function useFailure() {
  const { t } = useTranslation();
  return (failure: unknown) => {
    const fromServer = fieldErrors(failure);
    toast.error(Object.values(fromServer)[0] ?? t("admin.sales.detail.actionError"));
  };
}

/** "Valider (à livrer)" on a direct draft BL (D-305): its number now, the stock at the delivery. */
export function IssueButton({ sale, disabled }: { sale: SaleDetail; disabled: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const onFailure = useFailure();
  const issue = useMutation({
    mutationFn: () => issueSale(sale.id),
    onSuccess: async (saved) => {
      toast.success(t("admin.sales.direct.issued", { number: saved.number }));
      await refreshAfterSale(queryClient);
    },
    onError: onFailure,
  });
  return (
    <Button variant="primary" disabled={disabled || issue.isPending} onClick={() => issue.mutate()}>
      <Icon name="truck" />
      {t("admin.sales.direct.issue")}
    </Button>
  );
}

/** A direct BL "à livrer": delivered as written, in part, or not delivered (D-305). */
export function DirectDeliveryButtons({ sale, disabled }: { sale: SaleDetail; disabled: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const onFailure = useFailure();
  const [mode, setMode] = useState<"full" | "part" | "none" | null>(null);
  const [kilos, setKilos] = useState<Record<number, string>>({});
  const [note, setNote] = useState("");
  const done = async (saved: SaleDetail) => {
    toast.success(
      t(
        `admin.sales.direct.done.${saved.status === "cancelled" ? "none" : saved.delivery_status === "partial" ? "part" : "full"}`,
        { number: saved.number },
      ),
    );
    setMode(null);
    await refreshAfterSale(queryClient);
  };
  const deliver = useMutation({
    mutationFn: (lines: { line: number; quantity: string }[]) => deliverSale(sale.id, { lines, note: note.trim() }),
    onSuccess: done,
    onError: onFailure,
  });
  const notDelivered = useMutation({
    mutationFn: () => notDeliveredSale(sale.id, { note: note.trim() }),
    onSuccess: done,
    onError: onFailure,
  });
  const busy = disabled || deliver.isPending || notDelivered.isPending;
  const open = (next: "full" | "part" | "none") => {
    setNote("");
    setKilos(Object.fromEntries(sale.lines.map((line) => [line.id, line.quantity])));
    setMode(next);
  };

  return (
    <>
      <Button variant="primary" disabled={busy} onClick={() => open("full")}>
        <Icon name="check" />
        {t("admin.sales.direct.delivered")}
      </Button>
      <Button disabled={busy} onClick={() => open("part")}>
        {t("admin.sales.direct.partial")}
      </Button>
      <Button disabled={busy} onClick={() => open("none")}>
        {t("admin.sales.direct.notDelivered")}
      </Button>
      <Dialog open={mode !== null} onOpenChange={(value) => !value && setMode(null)}>
        <DialogContent>
          <DialogTitle>{t(`admin.sales.direct.title.${mode ?? "full"}`, { customer: sale.customer.name })}</DialogTitle>
          <DialogDescription>{t(`admin.sales.direct.body.${mode ?? "full"}`)}</DialogDescription>
          {mode === "part" && (
            <div className="flex flex-col gap-2">
              {sale.lines.map((line) => (
                <Field
                  key={line.id}
                  label={`${line.product.name} · ${formatQuantity(line.quantity)}`}
                  htmlFor={`kg-${line.id}`}
                >
                  <Input
                    id={`kg-${line.id}`}
                    inputMode="decimal"
                    value={kilos[line.id] ?? ""}
                    onChange={(event) => setKilos((current) => ({ ...current, [line.id]: event.target.value }))}
                  />
                </Field>
              ))}
            </div>
          )}
          {mode !== "full" && (
            <Field label={t("admin.sales.direct.note")} htmlFor="delivery-note">
              <Input
                id="delivery-note"
                value={note}
                maxLength={255}
                onChange={(event) => setNote(event.target.value)}
              />
            </Field>
          )}
          <DialogFooter>
            <Button onClick={() => setMode(null)}>{t("admin.sales.detail.keep")}</Button>
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => {
                if (mode === "none") notDelivered.mutate();
                else if (mode === "part")
                  deliver.mutate(
                    sale.lines.map((line) => ({
                      line: line.id,
                      quantity: (kilos[line.id] ?? line.quantity).trim().replace(",", ".") || "0",
                    })),
                  );
                else deliver.mutate([]);
              }}
            >
              {t(`admin.sales.direct.confirm.${mode ?? "full"}`)}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
