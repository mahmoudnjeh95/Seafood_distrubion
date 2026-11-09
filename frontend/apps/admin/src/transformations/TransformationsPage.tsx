import { useListTransformations } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, EmptyState, Icon, PageHeader, Pager, Table, Td, Th, useServerTable } from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { Link, useNavigate, useOutletContext } from "react-router";

import { StockTabs } from "../lib/StockTabs";
import { canRecordReceipts } from "../receipts/shared";

/** Stock › Transformations (D-304): cleaning, filleting, downgrading; each made a new lot. */
export function TransformationsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const table = useServerTable();
  const list = useListTransformations(table.params, { query: { placeholderData: keepPreviousData } });
  const rows = list.data?.results ?? [];

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.stock")} title={t("admin.transformations.title")}>
        {canRecordReceipts(session) && (
          <Button variant="primary" onClick={() => void navigate("/stock/transformations/nouvelle")}>
            <Icon name="plus" />
            {t("admin.transformations.add")}
          </Button>
        )}
      </PageHeader>
      <StockTabs />
      {list.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : rows.length === 0 ? (
        <EmptyState illustration="fish" title={t("admin.transformations.empty")}>
          {t("admin.transformations.emptyBody")}
        </EmptyState>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.transformations.columns.number")}</Th>
                <Th>{t("admin.transformations.columns.date")}</Th>
                <Th>{t("admin.transformations.columns.from")}</Th>
                <Th>{t("admin.transformations.columns.to")}</Th>
                <Th numeric className="max-[720px]:hidden">
                  {t("admin.transformations.columns.lost")}
                </Th>
                <Th numeric className="max-[720px]:hidden">
                  {t("admin.transformations.columns.fee")}
                </Th>
                <Th numeric>{t("admin.transformations.columns.cost")}</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <Td className="num font-semibold">{row.number}</Td>
                  <Td className="num whitespace-nowrap">{formatDate(row.done_on)}</Td>
                  <Td>
                    <Link to={`/stock/lots/${row.source_batch.id}`} className="font-semibold text-sea hover:underline">
                      {row.source_batch.number}
                    </Link>{" "}
                    {row.source_batch.product.name}
                    <div className="num text-[0.8rem] text-ink-2">{formatQuantity(row.source_quantity)}</div>
                  </Td>
                  <Td>
                    <Link to={`/stock/lots/${row.output_batch.id}`} className="font-semibold text-sea hover:underline">
                      {row.output_batch.number}
                    </Link>{" "}
                    {row.output_batch.product.name}
                    <div className="num text-[0.8rem] text-ink-2">{formatQuantity(row.output_quantity)}</div>
                  </Td>
                  <Td numeric className="max-[720px]:hidden">
                    {formatQuantity(row.weight_lost)}
                  </Td>
                  <Td numeric className="max-[720px]:hidden">
                    {formatMoney(row.fee)}
                  </Td>
                  <Td numeric className="font-semibold">
                    {formatMoney(row.output_batch.unit_cost)} / kg
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {list.data && <Pager {...table.pager(list.data.count)} />}
        </Card>
      )}
    </>
  );
}
