import type { LocationTotal, ProductStock } from "@frutti/api";
import { formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { cn, Pill, Table, Td, Th } from "@frutti/ui";
import { useState } from "react";
import { Link } from "react-router";

import type { StockView } from "./shared";

type SortKey = "name" | "quantity" | "average_cost";

/** "Cartes / Liste" switch of the stock page (D-198). */
export function StockViewSwitch({ view, onChange }: { view: StockView; onChange: (view: StockView) => void }) {
  const { t } = useTranslation();
  const option = (value: StockView) => (
    <button
      key={value}
      type="button"
      aria-pressed={view === value}
      onClick={() => onChange(value)}
      className={cn(
        "rounded-[7px] px-4 py-1.5 text-[0.9rem] font-semibold text-ink-2",
        view === value && "bg-surface text-ink shadow-card",
      )}
    >
      {t(`admin.stock.view.${value}`)}
    </button>
  );
  return (
    <div role="group" aria-label={t("admin.stock.view.label")} className="flex w-fit rounded-control bg-surface-2 p-1">
      {option("cards")}
      {option("list")}
    </div>
  );
}

/** The products of the stock page as one table: a row per product, a column per place holding stock (D-198). */
export function StockProductList({
  products,
  places,
}: {
  products: readonly ProductStock[];
  places: readonly LocationTotal[];
}) {
  const { t } = useTranslation();
  const [sort, setSort] = useState<{ key: SortKey; descending: boolean }>({ key: "name", descending: false });
  const kg = (stock: ProductStock, placeId: number) =>
    stock.locations.find((row) => row.location_id === placeId)?.quantity ?? "0.000";
  // Only the places that hold something get a column, so the table stays narrow.
  const columns = places.filter((place) => products.some((stock) => Number(kg(stock, place.id)) > 0));
  const rows = [...products].sort((a, b) => {
    const order =
      sort.key === "name"
        ? a.name.localeCompare(b.name, "fr")
        : Number(a[sort.key] ?? "-1") - Number(b[sort.key] ?? "-1");
    return sort.descending ? -order : order;
  });
  const header = (key: SortKey, label: string, numeric = false) => (
    <Th numeric={numeric} aria-sort={sort.key === key ? (sort.descending ? "descending" : "ascending") : "none"}>
      <button
        type="button"
        className="font-semibold uppercase"
        onClick={() => setSort((now) => ({ key, descending: now.key === key ? !now.descending : key !== "name" }))}
      >
        {label}
        {sort.key === key ? (sort.descending ? " ↓" : " ↑") : ""}
      </button>
    </Th>
  );
  return (
    <Table frozen>
      <thead>
        <tr>
          <Th>{t("admin.stock.list.reference")}</Th>
          {header("name", t("admin.stock.list.product"))}
          {header("quantity", t("admin.stock.total"), true)}
          {columns.map((place) => (
            <Th key={place.id} numeric>
              {place.name}
            </Th>
          ))}
          {header("average_cost", t("admin.stock.averageCost"), true)}
          <Th numeric>{t("admin.stock.lastCost")}</Th>
          <Th>{t("admin.stock.list.state")}</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((stock) => (
          <tr key={stock.id} className={cn(!stock.is_active && "opacity-70")}>
            <Td className="num text-ink-2">{stock.reference}</Td>
            <Td>
              <Link to={`/stock/produits/${stock.id}`} className="font-semibold text-sea hover:underline">
                {stock.name}
              </Link>
            </Td>
            <Td numeric className="font-semibold">
              {formatQuantity(stock.quantity)}
            </Td>
            {columns.map((place) => (
              <Td key={place.id} numeric>
                {Number(kg(stock, place.id)) > 0 ? formatQuantity(kg(stock, place.id)) : "—"}
              </Td>
            ))}
            <Td numeric>{stock.average_cost === null ? "—" : formatMoney(stock.average_cost)}</Td>
            <Td numeric>{stock.last_cost === null ? "—" : formatMoney(stock.last_cost)}</Td>
            <Td>
              {stock.is_low ? (
                <Pill tone="bad">{t("admin.stock.low")}</Pill>
              ) : (
                <Pill tone="good">{t("admin.stock.enough")}</Pill>
              )}
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
