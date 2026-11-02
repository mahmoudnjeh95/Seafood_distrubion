import {
  adjustStock,
  type ProductStockDetail,
  type StockAdjustmentWriteDirectionEnum,
  useListLocations,
} from "@frutti/api";
import { formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";

import { fieldErrors } from "../lib/errors";

type Errors = Partial<Record<"location" | "batch" | "quantity" | "reason" | "detail", string>>;

// The screens that show stock or prices: refreshed after an adjustment, since its average price moves.
const REFRESHED = ["/api/v1/stock", "/api/v1/price-board", "/api/v1/batches"];

/** Kilos put into a lot at a place, or taken out of it, by hand, with the reason. The lot keeps its cost, so the
 * product's average purchase price is worked out again from the stock on hand: the success message shows it
 * before and after. */
export function AdjustStockDialog({ stock, onDone }: { stock: ProductStockDetail; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const locations = useListLocations({ status: "active" });
  const [direction, setDirection] = useState<StockAdjustmentWriteDirectionEnum>("add");
  const [location, setLocation] = useState("");
  const [batch, setBatch] = useState("");
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Errors>({});

  const save = useMutation({
    mutationFn: (kilos: string) =>
      adjustStock({
        location: Number(location),
        batch: Number(batch),
        direction,
        quantity: kilos,
        reason: reason.trim(),
      }),
    onSuccess: async (answer) => {
      const before = stock.average_cost ? formatMoney(stock.average_cost) : t("admin.stock.none");
      const after = answer.average_cost ? formatMoney(answer.average_cost) : t("admin.stock.none");
      toast.success(t("admin.stock.product.adjust.saved", { before, after }));
      await queryClient.invalidateQueries({
        predicate: (query) => {
          const key = query.queryKey[0];
          return typeof key === "string" && REFRESHED.some((prefix) => key.startsWith(prefix));
        },
      });
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.stock.product.adjust.error") });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    const kilos = parseDecimalInput(quantity, 3);
    if (!location) found.location = t("admin.stock.product.adjust.required");
    if (!batch) found.batch = t("admin.stock.product.adjust.batchRequired");
    if (kilos === null || Number(kilos) <= 0) found.quantity = t("admin.stock.product.adjust.quantityInvalid");
    if (!reason.trim()) found.reason = t("admin.stock.product.adjust.reasonRequired");
    setErrors(found);
    if (Object.keys(found).length === 0 && kilos !== null) save.mutate(kilos);
  }

  return (
    <DialogContent>
      <DialogTitle>{t("admin.stock.product.adjust.title", { name: stock.name })}</DialogTitle>
      <DialogDescription>{t("admin.stock.product.adjust.hint")}</DialogDescription>
      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Field label={t("admin.stock.product.adjust.direction")} htmlFor={`${formId}-direction`}>
          <Select value={direction} onValueChange={(value) => setDirection(value as StockAdjustmentWriteDirectionEnum)}>
            <SelectTrigger id={`${formId}-direction`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="add">{t("admin.stock.product.adjust.add")}</SelectItem>
              <SelectItem value="remove">{t("admin.stock.product.adjust.remove")}</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("admin.stock.product.adjust.place")} htmlFor={`${formId}-place`} error={errors.location}>
          <Select value={location} onValueChange={setLocation}>
            <SelectTrigger id={`${formId}-place`} aria-invalid={errors.location ? true : undefined}>
              <SelectValue placeholder={t("admin.stock.product.adjust.placeHint")} />
            </SelectTrigger>
            <SelectContent>
              {(locations.data ?? []).map((place) => (
                <SelectItem key={place.id} value={String(place.id)}>
                  {place.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("admin.stock.product.adjust.batch")} htmlFor={`${formId}-batch`} error={errors.batch}>
          {stock.batches.length === 0 ? (
            <p className="text-[0.88rem] text-ink-2">{t("admin.stock.product.adjust.noBatches")}</p>
          ) : (
            <Select value={batch} onValueChange={setBatch}>
              <SelectTrigger id={`${formId}-batch`} aria-invalid={errors.batch ? true : undefined}>
                <SelectValue placeholder={t("admin.stock.product.adjust.batchHint")} />
              </SelectTrigger>
              <SelectContent>
                {stock.batches.map((row) => (
                  <SelectItem key={row.batch_id} value={String(row.batch_id)}>
                    {`${row.number} · ${row.supplier_name} · ${formatMoney(row.unit_cost)} · ${formatQuantity(row.quantity)}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Field>
        <Field label={t("admin.stock.product.adjust.quantity")} htmlFor={`${formId}-kilos`} error={errors.quantity}>
          <Input
            id={`${formId}-kilos`}
            inputMode="decimal"
            className="num text-end"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            aria-invalid={errors.quantity ? true : undefined}
            autoComplete="off"
          />
        </Field>
        {direction === "add" && <p className="text-[0.82rem] text-ink-2">{t("admin.stock.product.adjust.costNote")}</p>}
        <Field label={t("admin.stock.product.adjust.reason")} htmlFor={`${formId}-reason`} error={errors.reason}>
          <Input
            id={`${formId}-reason`}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            aria-invalid={errors.reason ? true : undefined}
            autoComplete="off"
          />
        </Field>
      </form>
      {errors.detail && (
        <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
          {errors.detail}
        </p>
      )}
      <DialogFooter className="items-center">
        <Button onClick={onDone}>{t("admin.stock.product.adjust.cancel")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={save.isPending}>
          {t("admin.stock.product.adjust.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
