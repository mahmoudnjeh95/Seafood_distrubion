import { useGetLotRecall } from "@frutti/api";
import { formatDate, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, EmptyState, Icon, PageHeader, Table, Td, Th } from "@frutti/ui";
import { Link, useParams } from "react-router";

/** The recall sheet of one lot (D-302): its origin, who kept kilos of it with their phone, and where the rest is.
 * Printed from the browser. */
export function LotRecallPage() {
  const { t } = useTranslation();
  const batchId = Number(useParams().batchId);
  const recall = useGetLotRecall(batchId);
  const back = (
    <Link to={`/stock/lots/${batchId}`} className="text-[0.85rem] font-semibold text-sea hover:underline print:hidden">
      {t("admin.stock.recall.back")}
    </Link>
  );
  if (recall.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!recall.data) {
    return (
      <>
        {back}
        <EmptyState illustration="fish" title={t("admin.stock.batch.notFound")} />
      </>
    );
  }
  const data = recall.data;
  const total = data.customers.reduce((sum, row) => sum + Number(row.quantity), 0);
  const origin = [
    data.scientific_name,
    data.catch_area && t("admin.stock.recall.zone", { zone: data.catch_area }),
    data.production_method && t(`admin.stock.origin.methods.${data.production_method as "wild" | "farmed"}`),
    data.origin,
    data.health_approval && t("admin.stock.recall.approval", { number: data.health_approval }),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      {back}
      <PageHeader
        eyebrow={`${data.product_name} · ${data.supplier_name}`}
        title={t("admin.stock.recall.title", { number: data.batch_number })}
      >
        <Button className="print:hidden" onClick={() => window.print()}>
          <Icon name="receipt" />
          {t("admin.stock.recall.print")}
        </Button>
      </PageHeader>
      <Card>
        <p>
          {t("admin.stock.recall.received", { day: formatDate(data.received_on) })}
          {data.use_by && ` · ${t("admin.stock.recall.useBy", { day: formatDate(data.use_by) })}`}
        </p>
        {origin && <p className="text-ink-2">{origin}</p>}
      </Card>
      <Card className="p-2">
        <CardTitle className="px-2.5 pt-2">
          {t("admin.stock.recall.customers", {
            count: data.customers.length,
            quantity: formatQuantity(total.toFixed(3)),
          })}
        </CardTitle>
        {data.customers.length === 0 ? (
          <p className="p-2.5 text-ink-2">{t("admin.stock.recall.noCustomer")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.stock.recall.customer")}</Th>
                <Th>{t("admin.stock.recall.phone")}</Th>
                <Th numeric>{t("admin.stock.recall.quantity")}</Th>
                <Th>{t("admin.stock.recall.when")}</Th>
                <Th>{t("admin.stock.recall.sales")}</Th>
              </tr>
            </thead>
            <tbody>
              {data.customers.map((row) => (
                <tr key={row.customer_id}>
                  <Td>
                    <Link to={`/clients/${row.customer_id}`} className="font-semibold text-sea hover:underline">
                      {row.customer_name}
                    </Link>
                    {row.city && <div className="text-[0.8rem] text-ink-2">{row.city}</div>}
                  </Td>
                  <Td className="num">{row.phone || "—"}</Td>
                  <Td numeric className="font-semibold">
                    {formatQuantity(row.quantity)}
                  </Td>
                  <Td className="num whitespace-nowrap">
                    {formatDate(row.first_on)}
                    {row.last_on !== row.first_on && ` → ${formatDate(row.last_on)}`}
                  </Td>
                  <Td className="num">{row.sales.join(", ")}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Card>
        <CardTitle>{t("admin.stock.recall.inStock")}</CardTitle>
        {data.in_stock.length === 0 ? (
          <p className="text-ink-2">{t("admin.stock.recall.nothingLeft")}</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {data.in_stock.map((row) => (
              <li key={row.location_id} className="flex justify-between gap-4">
                <span>{row.location_name}</span>
                <span className="num font-semibold">{formatQuantity(row.quantity)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
