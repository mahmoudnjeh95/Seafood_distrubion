import { ApiError, useGetProductStock, useListLocations, useListMovements } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Dialog, Icon, PageHeader, Pill, Table, Td, Th } from "@frutti/ui";
import { useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { StockTabs } from "../lib/StockTabs";
import { AdjustStockDialog } from "./AdjustStockDialog";
import { MovementsTable } from "./MovementsTable";
import { PurchasePrices } from "./StockProductCard";

const HISTORY_SIZE = 20;

/** One product: totals and purchase prices, the batches still on hand, and the latest movements. */
export function ProductStockPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const productId = Number(useParams().productId);
  const stock = useGetProductStock(productId);
  const places = useListLocations({ status: "all" });
  const movements = useListMovements({ product: productId, limit: HISTORY_SIZE });
  const [adjusting, setAdjusting] = useState(false);
  // Adjusting by hand is for the owner and the manager; the server refuses the others too.
  const canAdjust = session.role === "owner" || session.role === "manager";

  const back = (
    <Link to="/stock" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.stock.product.back")}
    </Link>
  );

  if (stock.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (stock.isError || !stock.data) {
    const missing = stock.error instanceof ApiError && stock.error.status === 404;
    return (
      <>
        {back}
        <p role="alert" className="text-bad">
          {t(missing ? "admin.stock.product.notFound" : "admin.stock.loadError")}
        </p>
      </>
    );
  }
  const data = stock.data;
  const placeName = (id: number) => (places.data ?? []).find((place) => place.id === id)?.name ?? String(id);

  return (
    <>
      {back}
      <PageHeader eyebrow={data.reference} title={t("admin.stock.product.title", { name: data.name })}>
        {data.is_low ? (
          <Pill tone="bad">{t("admin.stock.low")}</Pill>
        ) : (
          <Pill tone="good">{t("admin.stock.enough")}</Pill>
        )}
      </PageHeader>
      <StockTabs />
      {canAdjust && (
        <div>
          <Button onClick={() => setAdjusting(true)}>
            <Icon name="plus" />
            {t("admin.stock.product.adjust.open")}
          </Button>
        </div>
      )}
      <Dialog open={adjusting} onOpenChange={setAdjusting}>
        {adjusting && <AdjustStockDialog stock={data} onDone={() => setAdjusting(false)} />}
      </Dialog>

      <Card className="grid gap-4 p-4 sm:grid-cols-3" role="region" aria-label={t("admin.stock.product.summary")}>
        <div>
          <p className="text-[0.72rem] font-semibold text-ink-2">{t("admin.stock.product.quantity")}</p>
          <p className="num text-[1.4rem] font-bold">{formatQuantity(data.quantity)}</p>
          <p className="text-[0.8rem] text-ink-2">
            {t("admin.stock.minimum", { quantity: formatQuantity(data.min_stock) })}
          </p>
        </div>
        <div className="sm:col-span-2">
          <PurchasePrices stock={data} />
          <p className="mt-1 text-[0.78rem] text-ink-2">
            {t("admin.stock.product.averageHint")} {t("admin.stock.product.lastHint")}
          </p>
        </div>
      </Card>

      <section aria-labelledby="locations-title" className="flex flex-col gap-2">
        <h2 id="locations-title">{t("admin.stock.product.locations")}</h2>
        <div className="flex flex-wrap gap-3">
          {data.locations.map((row) => (
            <Card key={row.location_id} className="min-w-36 p-3">
              <p className="text-[0.78rem] font-semibold text-ink-2">{placeName(row.location_id)}</p>
              <p className="num font-bold">{formatQuantity(row.quantity)}</p>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby="batches-title" className="flex flex-col gap-2">
        <h2 id="batches-title">{t("admin.stock.product.batches")}</h2>
        {data.batches.length === 0 ? (
          <p className="text-ink-2">{t("admin.stock.product.noBatches")}</p>
        ) : (
          <Card className="p-2">
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.stock.product.columns.batch")}</Th>
                  <Th className="max-[720px]:hidden">{t("admin.stock.product.columns.supplier")}</Th>
                  <Th>{t("admin.stock.product.columns.received")}</Th>
                  <Th numeric>{t("admin.stock.product.columns.cost")}</Th>
                  <Th numeric>{t("admin.stock.product.columns.quantity")}</Th>
                  <Th numeric className="max-[720px]:hidden">
                    {t("admin.stock.product.columns.value")}
                  </Th>
                  <Th className="max-[720px]:hidden">{t("admin.stock.product.columns.where")}</Th>
                </tr>
              </thead>
              <tbody>
                {data.batches.map((batch) => (
                  <tr key={batch.batch_id}>
                    <Td className="num whitespace-nowrap">
                      <Link to={`/stock/lots/${batch.batch_id}`} className="font-semibold hover:underline">
                        {batch.number}
                      </Link>
                    </Td>
                    <Td className="max-[720px]:hidden">{batch.supplier_name}</Td>
                    <Td className="num whitespace-nowrap">{formatDate(batch.received_on)}</Td>
                    <Td numeric>{formatMoney(batch.unit_cost)}</Td>
                    <Td numeric>{formatQuantity(batch.quantity)}</Td>
                    <Td numeric className="max-[720px]:hidden">
                      {formatMoney(batch.value)}
                    </Td>
                    <Td className="text-[0.85rem] text-ink-2 max-[720px]:hidden">
                      {batch.locations
                        .map((row) => `${row.location.name} (${formatQuantity(row.quantity)})`)
                        .join(" · ")}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        )}
      </section>

      <section aria-labelledby="history-title" className="flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="history-title">{t("admin.stock.product.history")}</h2>
          <Link
            to={`/stock/mouvements?product=${productId}`}
            className="text-[0.85rem] font-semibold text-sea hover:underline"
          >
            {t("admin.stock.product.allMovements")}
          </Link>
        </div>
        {movements.data && movements.data.results.length > 0 && (
          <Card className="p-2">
            <CardTitle className="sr-only">{t("admin.stock.product.history")}</CardTitle>
            <MovementsTable movements={movements.data.results} />
          </Card>
        )}
      </section>
    </>
  );
}
