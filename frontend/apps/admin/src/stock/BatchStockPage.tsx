import type { Session } from "@frutti/auth";
import { ApiError, useGetBatch, useGetProductStock, useListMovements } from "@frutti/api";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Card, PageHeader } from "@frutti/ui";
import { type ReactNode } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { LotResultCard } from "../closing/LotResultCard";
import { SettlementCard } from "../closing/SettlementCard";
import { LotCostsCard } from "../expenses/LotCostsCard";
import { LotPartnerPill } from "../partnerships/LotPartnerPill";
import { PartnershipSection } from "../partnerships/PartnershipSection";
import { canReadResults } from "../partnerships/shared";
import { BatchSalesSection } from "../sales/BatchSalesSection";
import { canRecordReceipts } from "../receipts/shared";
import { LotOriginCard } from "./LotOriginCard";
import { MovementsTable } from "./MovementsTable";

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className="break-words">{children}</dd>
    </div>
  );
}

/** One batch: where it comes from, where it is now, and every movement that touched it. */
export function BatchStockPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const batchId = Number(useParams().batchId);
  const batch = useGetBatch(batchId);
  const productId = batch.data?.product.id;
  const stock = useGetProductStock(productId ?? 0, { query: { enabled: productId !== undefined } });
  const movements = useListMovements({ batch: batchId, limit: 200 });

  const back = (id?: number) => (
    <Link
      to={id === undefined ? "/stock" : `/stock/produits/${id}`}
      className="text-[0.85rem] font-semibold text-sea hover:underline"
    >
      {t("admin.stock.product.back")}
    </Link>
  );

  if (batch.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (batch.isError || !batch.data) {
    const missing = batch.error instanceof ApiError && batch.error.status === 404;
    return (
      <>
        {back()}
        <p role="alert" className="text-bad">
          {t(missing ? "admin.stock.batch.notFound" : "admin.stock.loadError")}
        </p>
      </>
    );
  }
  const data = batch.data;
  const held = stock.data?.batches.find((row) => row.batch_id === batchId);

  return (
    <>
      {back(data.product.id)}
      <PageHeader eyebrow={data.product.name} title={t("admin.stock.batch.title", { number: data.number })}>
        {canReadResults(session) && <LotPartnerPill batchId={batchId} />}
      </PageHeader>

      <Card className="p-4">
        <dl className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(11rem,1fr))]">
          <Detail label={t("admin.stock.batch.product")}>
            <Link to={`/stock/produits/${data.product.id}`} className="font-semibold text-sea hover:underline">
              {data.product.name}
            </Link>
          </Detail>
          <Detail label={t("admin.stock.batch.lot")}>
            <Link to={`/stock/lot-complet/${data.lot}`} className="font-semibold text-sea hover:underline">
              {t("admin.stock.batch.lotLine", { number: data.lot_number, line: data.line_number })}
            </Link>
          </Detail>
          <Detail label={t("admin.stock.batch.supplier")}>{data.supplier.name}</Detail>
          <Detail label={t("admin.stock.batch.received")}>{formatDate(data.received_on)}</Detail>
          <Detail label={t("admin.stock.batch.reference")}>{data.receipt_reference || t("admin.stock.none")}</Detail>
          <Detail label={t("admin.stock.batch.cost")}>
            <span className="num">{formatMoney(data.unit_cost)}</span> {t("admin.stock.perKg")}
          </Detail>
          <Detail label={t("admin.stock.batch.useBy")}>
            {data.use_by ? formatDate(data.use_by) : t("admin.stock.none")}
          </Detail>
          <Detail label={t("admin.stock.batch.onHand")}>
            <span className="num font-semibold">{formatQuantity(held?.quantity ?? "0")}</span>
            {held && (
              <span className="block text-[0.85rem] text-ink-2">
                {held.locations.map((row) => `${row.location.name} (${formatQuantity(row.quantity)})`).join(" · ")}
              </span>
            )}
          </Detail>
        </dl>
      </Card>

      <LotOriginCard
        key={`${data.catch_area}|${data.production_method}|${data.origin}`}
        batch={data}
        canEdit={canRecordReceipts(session)}
      />

      {/* P6-T01 / P6-T02: the owner's and accountant's view of the lot's partner and result */}
      {canReadResults(session) && (
        <PartnershipSection
          batch={{
            id: batchId,
            number: data.number,
            origin: held
              ? { supplier: data.supplier.name, quantity: held.quantity, unitCost: data.unit_cost, total: held.value }
              : undefined,
          }}
          session={session}
        />
      )}
      {canReadResults(session) && <LotResultCard batchId={batchId} session={session} />}
      {/* P6-T03: settlement with the partner (capital back ± share), late costs, the three balances */}
      {canReadResults(session) && <SettlementCard batchId={batchId} number={data.number} session={session} />}
      <BatchSalesSection batchId={batchId} />
      <LotCostsCard batchId={batchId} session={session} />

      <section aria-labelledby="batch-history" className="flex flex-col gap-2">
        <h2 id="batch-history">{t("admin.stock.batch.history")}</h2>
        {movements.data && (
          <Card className="p-2">
            <MovementsTable movements={movements.data.results} />
          </Card>
        )}
      </section>
    </>
  );
}
