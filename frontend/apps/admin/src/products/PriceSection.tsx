import { type Product, setProductPrice, useListProductPrices } from "@frutti/api";
import { formatDateTime, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Field, MoneyInput, Pill, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { refreshProducts } from "./shared";

/** The sale price history of a product, and a new price from now. Old prices are never changed (D-020). */
export function PriceSection({ product, canEdit }: { product: Product; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const prices = useListProductPrices(product.id);
  const [price, setPrice] = useState("");
  const [error, setError] = useState<string>();

  const apply = useMutation({
    mutationFn: (value: string) => setProductPrice(product.id, { price: value }),
    onSuccess: async () => {
      setPrice("");
      toast.success(t("admin.products.prices.applied"));
      await refreshProducts(queryClient);
    },
    onError: (failure) => setError(fieldErrors(failure).price ?? t("admin.products.form.error")),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = parseDecimalInput(price, 3);
    if (value === null) {
      setError(t("admin.products.form.invalidNumber", { places: 3 }));
      return;
    }
    setError(undefined);
    apply.mutate(value);
  }

  // The server says which price is in force; the history is newest first, so the ones above it are planned.
  const history = prices.data ?? [];
  const inForceIndex = history.findIndex((entry) => entry.valid_from === product.current_price_from);

  return (
    <section className="flex flex-col gap-3" aria-labelledby="price-section-title">
      <h3 id="price-section-title">{t("admin.products.prices.title")}</h3>
      {canEdit && product.is_active && (
        <form onSubmit={submit} className="flex flex-wrap items-end gap-2" noValidate>
          <Field
            label={t("admin.products.prices.newPrice")}
            htmlFor="new-price"
            error={error}
            className="min-w-40 flex-1"
          >
            <MoneyInput
              id="new-price"
              inputMode="decimal"
              autoComplete="off"
              className="num"
              value={price}
              aria-invalid={error ? true : undefined}
              onChange={(event) => setPrice(event.target.value)}
            />
          </Field>
          <Button type="submit" disabled={apply.isPending || price.trim() === ""}>
            {t("admin.products.prices.apply")}
          </Button>
          <p className="w-full text-[0.8rem] text-ink-2">{t("admin.products.prices.hint")}</p>
        </form>
      )}
      <ul className="flex flex-col divide-y divide-line rounded-control border border-line">
        {history.map((entry, index) => {
          const planned = inForceIndex === -1 ? product.current_price_from === null : index < inForceIndex;
          return (
            <li key={entry.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-2">
              <span className="num font-semibold">{formatMoney(entry.price)}</span>
              <span className="text-[0.82rem] text-ink-2">
                {t(planned ? "admin.products.prices.startsAt" : "admin.products.prices.from", {
                  date: formatDateTime(entry.valid_from),
                })}
                {entry.created_by && ` · ${t("admin.products.prices.by", { name: entry.created_by })}`}
              </span>
              {index === inForceIndex && <Pill tone="good">{t("admin.products.prices.current")}</Pill>}
              {planned && <Pill tone="warn">{t("admin.products.prices.planned")}</Pill>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
