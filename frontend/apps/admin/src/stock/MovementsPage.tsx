import { type StockMovementKindEnum, useListLocations, useListMovements, useListProducts } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Card, EmptyState, Input, PageHeader, Pager, useServerTable } from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { StockTabs } from "../lib/StockTabs";
import { MovementsTable } from "./MovementsTable";
import { MOVEMENT_KINDS } from "./shared";

const SELECT_CLASSES = "rounded-control border border-line bg-surface px-3 py-2 text-ink";
const LABEL_CLASSES = "flex flex-col gap-1 text-[0.78rem] font-semibold text-ink-2";

/** The whole stock ledger, filtered by place, product, type and dates (P1-T11). */
export function MovementsPage() {
  const { t } = useTranslation();
  const [location, setLocation] = useState("");
  // The product page links here with its product already chosen.
  const [params] = useSearchParams();
  const [product, setProduct] = useState(params.get("product") ?? "");
  const [kind, setKind] = useState<StockMovementKindEnum | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const table = useServerTable();

  const locations = useListLocations({ status: "all" });
  const products = useListProducts({ status: "all" });
  const movements = useListMovements(
    {
      ...table.params,
      ...(location ? { location: Number(location) } : {}),
      ...(product ? { product: Number(product) } : {}),
      ...(kind ? { kind } : {}),
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo ? { date_to: dateTo } : {}),
    },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = movements.data;
  const list = page?.results ?? [];
  const filtering = location !== "" || product !== "" || kind !== "" || dateFrom !== "" || dateTo !== "";

  // Any filter change goes back to the first page.
  const change = (set: (value: string) => void) => (event: { target: { value: string } }) => {
    set(event.target.value);
    table.backToFirstPage();
  };
  const reset = () => {
    setLocation("");
    setProduct("");
    setKind("");
    setDateFrom("");
    setDateTo("");
    table.backToFirstPage();
  };

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.goods")} title={t("admin.stock.movements.title")} />
      <StockTabs />
      <p className="text-ink-2">{t("admin.stock.movements.intro")}</p>

      <Card className="filter-bar flex flex-wrap items-end gap-3 p-3">
        <label className={LABEL_CLASSES}>
          {t("admin.stock.movements.location")}
          <select className={SELECT_CLASSES} value={location} onChange={change(setLocation)}>
            <option value="">{t("admin.stock.movements.allLocations")}</option>
            {(locations.data ?? [])
              .filter((place) => place.is_active || String(place.id) === location)
              .map((place) => (
                <option key={place.id} value={place.id}>
                  {place.name}
                </option>
              ))}
          </select>
        </label>
        <label className={LABEL_CLASSES}>
          {t("admin.stock.movements.product")}
          <select className={SELECT_CLASSES} value={product} onChange={change(setProduct)}>
            <option value="">{t("admin.stock.movements.allProducts")}</option>
            {(products.data ?? [])
              .filter((item) => item.is_active || String(item.id) === product)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
          </select>
        </label>
        <label className={LABEL_CLASSES}>
          {t("admin.stock.movements.kind")}
          <select
            className={SELECT_CLASSES}
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as StockMovementKindEnum | "");
              table.backToFirstPage();
            }}
          >
            <option value="">{t("admin.stock.movements.allKinds")}</option>
            {MOVEMENT_KINDS.map((value) => (
              <option key={value} value={value}>
                {t(`admin.stock.movements.kinds.${value}`)}
              </option>
            ))}
          </select>
        </label>
        <label className={LABEL_CLASSES}>
          {t("admin.stock.movements.from")}
          <Input type="date" value={dateFrom} max={dateTo || undefined} onChange={change(setDateFrom)} />
        </label>
        <label className={LABEL_CLASSES}>
          {t("admin.stock.movements.to")}
          <Input type="date" value={dateTo} min={dateFrom || undefined} onChange={change(setDateTo)} />
        </label>
        {filtering && <Button onClick={reset}>{t("admin.stock.movements.reset")}</Button>}
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.stock.movements.count", { count: page.count })}
        </span>
      </Card>

      {movements.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : movements.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.stock.movements.noMatch")}</p>
        ) : (
          <EmptyState illustration="fridge" title={t("admin.stock.movements.empty")} />
        )
      ) : (
        <Card className="p-2">
          <MovementsTable movements={list} />
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      )}
    </>
  );
}
