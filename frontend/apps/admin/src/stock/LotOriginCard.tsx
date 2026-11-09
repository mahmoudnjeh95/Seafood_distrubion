import { type Batch, type BatchOriginWrite, updateBatchOrigin } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Input,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { Link } from "react-router";

type Method = BatchOriginWrite["production_method"];

/** Where a lot comes from (D-299): Latin name, FAO zone or farm, wild or farmed, boat or port, health approval;
 * completed later by the office, and the lot's recall sheet. */
export function LotOriginCard({ batch, canEdit }: { batch: Batch; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [open, setOpen] = useState(false);
  const [catchArea, setCatchArea] = useState(batch.catch_area);
  const [method, setMethod] = useState<Method>(batch.production_method as Method);
  const [origin, setOrigin] = useState(batch.origin);
  const save = useMutation({
    mutationFn: (body: BatchOriginWrite) => updateBatchOrigin(batch.id, body),
    onSuccess: async () => {
      toast.success(t("admin.stock.origin.saved"));
      await queryClient.invalidateQueries({ queryKey: [`/api/v1/batches/${batch.id}`] });
      setOpen(false);
    },
    onError: () => toast.error(t("admin.stock.origin.failed")),
  });
  const none = t("admin.stock.none");
  const methodLabel = batch.production_method ? t(`admin.stock.origin.methods.${batch.production_method}`) : none;

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate({ catch_area: catchArea.trim(), production_method: method, origin: origin.trim() });
  }

  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <CardTitle className="mb-0">{t("admin.stock.origin.title")}</CardTitle>
        <div className="flex gap-2">
          <Button asChild variant="ghost">
            <Link to={`/stock/lots/${batch.id}/rappel`}>{t("admin.stock.origin.recall")}</Link>
          </Button>
          {canEdit && <Button onClick={() => setOpen(true)}>{t("admin.stock.origin.edit")}</Button>}
        </div>
      </div>
      <dl className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(11rem,1fr))]">
        {(
          [
            ["scientific", batch.product.scientific_name || none],
            ["catchArea", batch.catch_area || none],
            ["method", methodLabel],
            ["place", batch.origin || none],
            ["approval", batch.supplier.health_approval || none],
          ] as const
        ).map(([key, value]) => (
          <div key={key} className="flex flex-col gap-0.5">
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t(`admin.stock.origin.${key}`)}</dt>
            <dd className="break-words">{value}</dd>
          </div>
        ))}
      </dl>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[min(520px,calc(100vw-2rem))]">
          <DialogTitle>{t("admin.stock.origin.edit")}</DialogTitle>
          <DialogDescription>{t("admin.stock.origin.hint")}</DialogDescription>
          <form id={formId} onSubmit={submit} className="flex flex-col gap-3">
            <Field label={t("admin.stock.origin.catchArea")} htmlFor={`${formId}-area`}>
              <Input
                id={`${formId}-area`}
                value={catchArea}
                maxLength={60}
                onChange={(event) => setCatchArea(event.target.value)}
              />
            </Field>
            <Field label={t("admin.stock.origin.method")} htmlFor={`${formId}-method`}>
              <select
                id={`${formId}-method`}
                value={method}
                onChange={(event) => setMethod(event.target.value as Method)}
                className="rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
              >
                <option value="">{none}</option>
                <option value="wild">{t("admin.stock.origin.methods.wild")}</option>
                <option value="farmed">{t("admin.stock.origin.methods.farmed")}</option>
              </select>
            </Field>
            <Field label={t("admin.stock.origin.place")} htmlFor={`${formId}-place`}>
              <Input
                id={`${formId}-place`}
                value={origin}
                maxLength={100}
                onChange={(event) => setOrigin(event.target.value)}
              />
            </Field>
          </form>
          <DialogFooter>
            <Button onClick={() => setOpen(false)}>{t("admin.stock.origin.cancel")}</Button>
            <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
              {t("admin.stock.origin.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
