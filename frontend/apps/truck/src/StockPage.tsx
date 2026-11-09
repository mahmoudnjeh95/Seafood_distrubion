import { useSession } from "@frutti/auth";
import { formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, EmptyState } from "@frutti/ui";
import { Link } from "react-router";

import { PricesAsOf } from "./PriceNotice";
import { ProductPhoto } from "./ProductPhoto";
import { TruckTemperatureCard } from "./TruckTemperatureCard";
import { pendingKilos, useQueue } from "./queue";
import { useTruckStock } from "./myStock";

const millimes = (value: string | number) => Math.round(Number(value) * 1000);
const fromMillimes = (value: number) => (value / 1000).toFixed(3);

// "Mon stock": what the truck holds now, product by product, minus what waits on the phone to be sent.
export function StockPage() {
  const { t } = useTranslation();
  const session = useSession();
  const truck = session.data?.truck ?? null;
  const stock = useTruckStock(truck !== null);
  const queue = useQueue();

  if (truck === null) {
    return (
      <EmptyState illustration="truck" title={t("truck.day.noTruck")}>
        {t("truck.sale.needTruck")}
      </EmptyState>
    );
  }
  // A failed refresh keeps the stock already shown: the error screen is for when there is nothing to show.
  if (stock.isError && stock.data === undefined) {
    return (
      <Card className="space-y-3">
        <p className="text-lg font-semibold">{t("truck.stock.failed")}</p>
        <Button size="lg" onClick={() => void stock.refetch()}>
          {t("truck.stock.retry")}
        </Button>
      </Card>
    );
  }
  if (stock.isPending) return <Card className="h-24 animate-pulse" aria-busy="true" />;

  const promised = pendingKilos(queue);
  const lines = stock.data
    .map((line) => {
      const waiting = millimes(promised[line.product_id] ?? 0);
      return { ...line, waiting, left: Math.max(millimes(line.quantity) - waiting, 0) };
    })
    .filter((line) => line.left > 0 || line.waiting > 0);
  if (lines.length === 0) {
    return (
      <EmptyState illustration="shrimp" title={t("truck.stock.empty")}>
        {t("truck.stock.emptyBody")}
      </EmptyState>
    );
  }
  const totalKg = lines.reduce((sum, line) => sum + line.left, 0);
  const worth = lines.reduce(
    (sum, line) => sum + (line.unit_price === null ? 0 : Math.round((line.left * millimes(line.unit_price)) / 1000)),
    0,
  );

  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2>{t("truck.stock.title")}</h2>
          <span className="text-xl font-bold">{formatQuantity(fromMillimes(totalKg))}</span>
        </div>
        <PricesAsOf updatedAt={stock.dataUpdatedAt} />
        <ul className="divide-y divide-line">
          {lines.map((line) => (
            <li key={line.product_id} className="flex items-center justify-between gap-3 py-3">
              <span className="flex min-w-0 items-center gap-3">
                <ProductPhoto url={line.photo_url} name={line.product_name} />
                <span className="min-w-0">
                  <span className="block text-lg font-semibold">{line.product_name}</span>
                  <span className="block text-sm text-ink-2">
                    {line.unit_price === null
                      ? t("truck.stock.noPrice")
                      : t("truck.stock.perKg", { price: formatMoney(line.unit_price) })}
                  </span>
                  {line.waiting > 0 ? (
                    <span className="block text-sm text-ink-2">
                      {t("truck.stock.waiting", { kg: formatQuantity(fromMillimes(line.waiting)) })}
                    </span>
                  ) : null}
                </span>
              </span>
              <span className="text-xl font-bold">{formatQuantity(fromMillimes(line.left))}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 flex items-baseline justify-between gap-3 border-t border-line pt-3">
          <span>{t("truck.stock.worth")}</span>
          <span className="font-bold">{formatMoney(fromMillimes(worth))}</span>
        </p>
      </Card>
      <TruckTemperatureCard />
      <Button asChild size="lg" className="py-4 text-lg">
        <Link to="/perte">{t("truck.stock.giveBack")}</Link>
      </Button>
    </div>
  );
}
