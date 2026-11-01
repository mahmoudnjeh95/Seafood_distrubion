import {
  getGetPriceBoardQueryKey,
  type PriceBoardRow,
  setPriceBoard,
  type SetPrices,
  useGetPriceBoard,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import {
  formatDateTime,
  formatMoney,
  formatPercent,
  formatQuantity,
  parseDecimalInput,
  useTranslation,
} from "@frutti/i18n";
import { Button, Card, EmptyState, MoneyInput, PageHeader, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useOutletContext } from "react-router";

import { marginPercent, subtract, toThousandths } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";

/** A server decimal as typed in a field: "42.000" → "42,000". */
function asInput(value: string | null): string {
  return value === null ? "" : value.replace(".", ",");
}

type Edit = { price?: string; min?: string };

/** What the field holds, parsed: undefined when empty, null when not a number. */
function parsed(text: string): string | null | undefined {
  return text.trim() === "" ? undefined : parseDecimalInput(text.trim(), 3);
}

function isPositive(value: string): boolean {
  return !value.startsWith("-") && /[1-9]/.test(value);
}

/** "Prix du jour": the sale price of every product in one go (D-049). */
export function PriceBoardPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const queryClient = useQueryClient();
  const canEdit = session.role === "owner" || session.role === "manager";
  const board = useGetPriceBoard();
  const [edits, setEdits] = useState<Record<number, Edit>>({});

  const rows = board.data?.rows ?? [];
  const textOf = (row: PriceBoardRow, field: "price" | "min"): string =>
    edits[row.product.id]?.[field] ?? asInput(field === "price" ? row.price : row.min_price);

  // Only the rows the person touched are sent; the server leaves unchanged prices alone anyway.
  function buildItems(): SetPrices["items"] | null {
    const items: SetPrices["items"] = [];
    for (const row of rows) {
      const edit = edits[row.product.id];
      if (!edit) continue;
      const item: SetPrices["items"][number] = { product: row.product.id };
      if (edit.price !== undefined) {
        const price = parsed(edit.price);
        if (price === null || (price !== undefined && !isPositive(price))) return null;
        if (price !== undefined) item.price = price;
      }
      if (edit.min !== undefined) {
        const min = parsed(edit.min);
        if (min === null || (min !== undefined && !isPositive(min))) return null;
        item.min_price = min ?? null;
      }
      items.push(item);
    }
    return items;
  }

  const save = useMutation({
    mutationFn: (items: SetPrices["items"]) => setPriceBoard({ items }),
    onSuccess: async (saved) => {
      setEdits({});
      queryClient.setQueryData(getGetPriceBoardQueryKey(), saved);
      await queryClient.invalidateQueries({
        predicate: (query) =>
          typeof query.queryKey[0] === "string" && String(query.queryKey[0]).startsWith("/api/v1/products"),
      });
      toast.success(t("admin.priceBoard.saved"));
      if (saved.below_minimum.length > 0) {
        toast.warning(t("admin.priceBoard.savedBelow", { count: saved.below_minimum.length }));
      }
    },
    onError: (failure) => toast.error(fieldErrors(failure).items ?? t("admin.priceBoard.error")),
  });

  const items = buildItems();
  const invalid = items === null;
  const dirty = Object.keys(edits).length > 0;

  function change(row: PriceBoardRow, field: "price" | "min", value: string) {
    setEdits((current) => ({ ...current, [row.product.id]: { ...current[row.product.id], [field]: value } }));
  }

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.sales")} title={t("admin.priceBoard.title")}>
        {canEdit && (
          <Button
            variant="primary"
            disabled={!dirty || invalid || save.isPending}
            onClick={() => items && save.mutate(items)}
          >
            {t("admin.priceBoard.save")}
          </Button>
        )}
      </PageHeader>
      <p className="text-ink-2">{canEdit ? t("admin.priceBoard.intro") : t("admin.priceBoard.readOnly")}</p>
      {invalid && (
        <p role="alert" className="text-bad">
          {t("admin.priceBoard.invalid")}
        </p>
      )}

      {board.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : board.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : rows.length === 0 ? (
        <EmptyState illustration="fish" title={t("admin.priceBoard.empty")}>
          {t("admin.priceBoard.emptyBody")}
        </EmptyState>
      ) : (
        <Card className="p-2">
          <Table frozen>
            <thead>
              <tr>
                <Th>{t("admin.priceBoard.columns.product")}</Th>
                <Th numeric>{t("admin.priceBoard.columns.stock")}</Th>
                <Th numeric>{t("admin.priceBoard.columns.lastCost")}</Th>
                <Th numeric>{t("admin.priceBoard.columns.averageCost")}</Th>
                <Th numeric>{t("admin.priceBoard.columns.price")}</Th>
                <Th numeric>{t("admin.priceBoard.columns.margin")}</Th>
                <Th numeric>{t("admin.priceBoard.columns.minimum")}</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const priceText = textOf(row, "price");
                const price = parsed(priceText);
                const minimum = parsed(textOf(row, "min"));
                // The preview follows what is typed; the server stays the reference.
                const shown = typeof price === "string" ? price : null;
                const margin = shown !== null && row.average_cost !== null ? subtract(shown, row.average_cost) : null;
                const percent =
                  shown !== null && row.average_cost !== null ? marginPercent(shown, row.average_cost) : null;
                const below =
                  typeof price === "string" &&
                  typeof minimum === "string" &&
                  isPositive(minimum) &&
                  toThousandths(price) < toThousandths(minimum);
                return (
                  <tr key={row.product.id}>
                    <Td>
                      <div className="font-semibold">{row.product.name}</div>
                      <div className="text-[0.8rem] text-ink-2">{row.product.reference}</div>
                      {row.todays_prices.length > 0 && (
                        <ul
                          aria-label={t("admin.priceBoard.todayPrices", { name: row.product.name })}
                          className="mt-1 flex flex-col gap-0.5 text-[0.78rem] text-ink-2"
                        >
                          {row.todays_prices.map((entry) => (
                            <li key={entry.valid_from}>
                              {t("admin.priceBoard.todayEntry", {
                                price: formatMoney(entry.price),
                                date: formatDateTime(entry.valid_from),
                                name: entry.created_by ?? "—",
                              })}
                            </li>
                          ))}
                        </ul>
                      )}
                    </Td>
                    <Td numeric>{formatQuantity(row.stock)}</Td>
                    <Td numeric>{row.last_cost === null ? "—" : formatMoney(row.last_cost)}</Td>
                    <Td numeric>{row.average_cost === null ? "—" : formatMoney(row.average_cost)}</Td>
                    <Td numeric>
                      <MoneyInput
                        inputMode="decimal"
                        autoComplete="off"
                        className="num w-28 text-end"
                        aria-label={t("admin.priceBoard.priceOf", { name: row.product.name })}
                        value={priceText}
                        disabled={!canEdit}
                        aria-invalid={price === null ? true : undefined}
                        onChange={(event) => change(row, "price", event.target.value)}
                      />
                      {below && (
                        <div className="mt-1">
                          <Pill tone="warn">{t("admin.priceBoard.belowMinimum")}</Pill>
                        </div>
                      )}
                    </Td>
                    <Td numeric>
                      {margin === null ? (
                        "—"
                      ) : (
                        <>
                          <div>{formatMoney(margin)}</div>
                          {percent !== null && (
                            <div className="text-[0.78rem] text-ink-2">{formatPercent(percent)}</div>
                          )}
                        </>
                      )}
                    </Td>
                    <Td numeric>
                      <MoneyInput
                        inputMode="decimal"
                        autoComplete="off"
                        className="num w-24 text-end"
                        aria-label={t("admin.priceBoard.minimumOf", { name: row.product.name })}
                        value={textOf(row, "min")}
                        disabled={!canEdit}
                        aria-invalid={minimum === null ? true : undefined}
                        onChange={(event) => change(row, "min", event.target.value)}
                      />
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </Card>
      )}
    </>
  );
}
