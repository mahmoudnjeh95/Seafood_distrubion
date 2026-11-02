import { useState } from "react";
import { type ListPartnershipsStatus, useListLotFigures, useListPartnerships } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Card,
  cn,
  EmptyState,
  Input,
  PageHeader,
  Pager,
  Pill,
  SortTh,
  Table,
  Td,
  Th,
  useTableView,
  useUrlState,
} from "@frutti/ui";

import { Link, useOutletContext } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { canReadResults, formatRate, STATUS_TONE } from "./shared";

type Filter = "live" | ListPartnershipsStatus;
const FILTERS: readonly Filter[] = ["live", "open", "closed", "settled", "cancelled"];

/** "Partenariats" (P6-T01): the partnership lots, open, closed, settled or cancelled, each with the partner's
 * capital now and their two rates; a row opens the lot page with its result. */
export function PartnershipsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const [filter, setFilter] = useState<Filter>("live");
  const [search, setSearch] = useUrlState("q");
  const debounced = useDebounced(search.trim(), 300);
  const allowed = canReadResults(session);
  const partnerships = useListPartnerships(
    { status: filter === "live" ? undefined : filter, search: debounced || undefined, limit: 200 },
    { query: { enabled: allowed } },
  );

  const rows = partnerships.data?.results ?? [];
  // The frozen figures of the closed lots on this page; an open lot has none (its result is live, on its page).
  const batchIds = rows.map((row) => row.batch.id).join(",");
  const figures = useListLotFigures({ batch_ids: batchIds }, { query: { enabled: allowed && batchIds !== "" } });
  const figureOf = (batchId: number) => figures.data?.find((figure) => figure.batch_id === batchId);

  const view = useTableView(rows, {
    lot: (row) => row.batch.number,
    product: (row) => row.batch.product_name,
    partner: (row) => row.partner.name,
    capital: (row) => Number(row.capital),
    status: (row) => row.status,
  });
  const sorting = { sort: view.sort, onSort: view.toggleSort };

  if (!allowed) {
    return (
      <>
        <PageHeader eyebrow={t("admin.partnerships.eyebrow")} title={t("admin.partnerships.title")} />
        <EmptyState illustration="mix" title={t("admin.lotResult.restricted")} />
      </>
    );
  }

  return (
    <>
      <PageHeader eyebrow={t("admin.partnerships.eyebrow")} title={t("admin.partnerships.title")} />
      <p className="text-ink-2">{t("admin.partnerships.intro")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label={t("admin.partnerships.filter")} className="flex rounded-control bg-surface-2 p-1">
          {FILTERS.map((choice) => (
            <button
              key={choice}
              type="button"
              aria-pressed={filter === choice}
              onClick={() => setFilter(choice)}
              className={cn(
                "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
                filter === choice && "bg-surface text-ink shadow-card",
              )}
            >
              {t(`admin.partnerships.filters.${choice}`)}
            </button>
          ))}
        </div>
        <Input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("admin.partnerships.search")}
          aria-label={t("admin.partnerships.search")}
          className="max-w-xs"
        />
      </div>
      <Card className="p-2">
        {partnerships.isPending ? (
          <p className="p-2 text-ink-2">{t("common.loading")}</p>
        ) : partnerships.isError ? (
          <p role="alert" className="p-2 text-bad">
            {t("admin.partnerships.loadError")}
          </p>
        ) : rows.length === 0 ? (
          <p className="p-2 text-ink-2">{t("admin.partnerships.empty")}</p>
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <SortTh sortKey="lot" {...sorting}>
                    {t("admin.partnerships.columns.lot")}
                  </SortTh>
                  <SortTh sortKey="product" {...sorting}>
                    {t("admin.partnerships.columns.product")}
                  </SortTh>
                  <SortTh sortKey="partner" {...sorting}>
                    {t("admin.partnerships.columns.partner")}
                  </SortTh>
                  <SortTh numeric sortKey="capital" {...sorting}>
                    {t("admin.partnerships.columns.capital")}
                  </SortTh>
                  <Th numeric>{t("admin.partnerships.columns.net")}</Th>
                  <Th numeric className="max-[720px]:hidden">
                    {t("admin.partnerships.columns.share")}
                  </Th>
                  <Th className="max-[720px]:hidden">{t("admin.partnerships.columns.rates")}</Th>
                  <SortTh sortKey="status" {...sorting}>
                    {t("admin.partnerships.columns.status")}
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {view.rows.map((row) => (
                  <tr key={row.id}>
                    <Td className="num whitespace-nowrap">
                      <Link to={`/stock/lots/${row.batch.id}`} className="font-semibold text-sea hover:underline">
                        {row.batch.number}
                      </Link>
                      <div className="text-[0.8rem] text-ink-2">{formatDate(row.batch.received_on)}</div>
                    </Td>
                    <Td>{row.batch.product_name}</Td>
                    <Td>{row.partner.name}</Td>
                    <Td numeric className="whitespace-nowrap">
                      {formatMoney(row.capital)}
                    </Td>
                    <Td numeric className="whitespace-nowrap">
                      {figureOf(row.batch.id) ? (
                        <span className={figureOf(row.batch.id)?.outcome === "loss" ? "text-bad" : undefined}>
                          {formatMoney(figureOf(row.batch.id)?.net_result ?? "0")}
                        </span>
                      ) : (
                        <span className="text-[0.8rem] text-ink-2">{t("admin.partnerships.notClosed")}</span>
                      )}
                    </Td>
                    <Td numeric className="whitespace-nowrap max-[720px]:hidden">
                      {figureOf(row.batch.id) ? formatMoney(figureOf(row.batch.id)?.partner_share ?? "0") : "—"}
                    </Td>
                    <Td className="num max-[720px]:hidden">
                      {t("admin.partnerships.rates", {
                        profit: formatRate(row.profit_rate),
                        loss: formatRate(row.loss_rate),
                      })}
                    </Td>
                    <Td>
                      <Pill tone={STATUS_TONE[row.status]}>{t(`admin.partnerships.statuses.${row.status}`)}</Pill>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pager {...view.pager} />
          </>
        )}
      </Card>
    </>
  );
}
