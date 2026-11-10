import { ApiError, useGetLot } from "@frutti/api";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Card, PageHeader, Table, Td, Th } from "@frutti/ui";
import { Link, useParams } from "react-router";

/** One purchase (D-320): its supplier and day, and each of its products with the kilos received, sold, lost and
 * still held. Each product opens its own page, where its sales, costs and result are. */
export function LotPage() {
  const { t } = useTranslation();
  const lotId = Number(useParams().lotId);
  const lot = useGetLot(lotId);

  const back = (
    <Link to="/stock" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.stock.product.back")}
    </Link>
  );

  if (lot.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (lot.isError || !lot.data) {
    const missing = lot.error instanceof ApiError && lot.error.status === 404;
    return (
      <>
        {back}
        <p role="alert" className="text-bad">
          {t(missing ? "admin.stock.batch.notFound" : "admin.stock.loadError")}
        </p>
      </>
    );
  }
  const data = lot.data;

  return (
    <>
      {back}
      <PageHeader eyebrow={data.supplier.name} title={t("admin.stock.batch.title", { number: data.number })} />

      <Card className="p-4">
        <dl className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(11rem,1fr))]">
          <div className="flex flex-col gap-0.5">
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.stock.batch.supplier")}</dt>
            <dd>
              <Link to={`/fournisseurs/${data.supplier.id}`} className="font-semibold text-sea hover:underline">
                {data.supplier.name}
              </Link>
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.stock.batch.received")}</dt>
            <dd>{formatDate(data.received_on)}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.stock.batch.reference")}</dt>
            <dd className="break-words">{data.receipt_reference || t("admin.stock.none")}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.stock.lot.purchaseValue")}</dt>
            <dd className="num font-semibold">{formatMoney(data.purchase_value)}</dd>
          </div>
        </dl>
      </Card>

      <section aria-labelledby="lot-lines" className="flex flex-col gap-2">
        <h2 id="lot-lines">{t("admin.stock.lot.lines", { count: data.lines.length })}</h2>
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.stock.lot.line")}</Th>
                <Th>{t("admin.stock.batch.product")}</Th>
                <Th numeric className="max-[720px]:hidden">
                  {t("admin.stock.batch.cost")}
                </Th>
                <Th numeric>{t("admin.stock.lot.received")}</Th>
                <Th numeric>{t("admin.stock.lot.sold")}</Th>
                <Th numeric className="max-[720px]:hidden">
                  {t("admin.stock.lot.lost")}
                </Th>
                <Th numeric>{t("admin.stock.batch.onHand")}</Th>
                <Th numeric className="max-[720px]:hidden">
                  {t("admin.stock.lot.purchaseValue")}
                </Th>
              </tr>
            </thead>
            <tbody>
              {data.lines.map((line) => (
                <tr key={line.batch_id}>
                  <Td className="num whitespace-nowrap">
                    <Link to={`/stock/lots/${line.batch_id}`} className="font-semibold text-sea hover:underline">
                      {line.number}
                    </Link>
                  </Td>
                  <Td>{line.product.name}</Td>
                  <Td numeric className="max-[720px]:hidden">
                    {formatMoney(line.unit_cost)}
                  </Td>
                  <Td numeric>{formatQuantity(line.received)}</Td>
                  <Td numeric>{formatQuantity(line.sold)}</Td>
                  <Td numeric className="max-[720px]:hidden">
                    {formatQuantity(line.lost)}
                  </Td>
                  <Td numeric>{formatQuantity(line.on_hand)}</Td>
                  <Td numeric className="max-[720px]:hidden">
                    {formatMoney(line.purchase_value)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <p className="text-[0.85rem] text-ink-2">{t("admin.stock.lot.hint")}</p>
      </section>
    </>
  );
}
