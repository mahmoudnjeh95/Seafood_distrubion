import { type SaleDetail, useListSales } from "@frutti/api";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@frutti/i18n";
import { Card, CardTitle, EmptyState, Input, PageHeader, Pill, Table, Td, Th, useUrlState } from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { subtract } from "../lib/decimal";
import { useDebounced } from "../lib/useDebounced";
import { TresorerieRibbon } from "./TresorerieRibbon";

/** What was collected on an opening balance so far: its amount less what is still owed. */
const collected = (total: string, due: string) => subtract(total, due);

/**
 * Trésorerie › Encaissement › Créances clients › Soldes d'ouverture (D-283): what each customer owed when the
 * application started (OUV), apart from the delivery notes. No goods, no stock, no turnover and no margin: only
 * the amount, what was collected on it and what is left. The treasurer collects it in Règlements clients.
 */
export function OpeningBalancesPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useUrlState("q");
  const query = useDebounced(search.trim());
  const list = useListSales(
    { opening: "only", limit: 500, ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const rows = list.data?.results ?? [];

  return (
    <>
      <TresorerieRibbon active="soldesOuverture" />
      <PageHeader eyebrow={t("admin.openingBalances.eyebrow")} title={t("admin.openingBalances.title")} />
      <p className="text-ink-2">{t("admin.openingBalances.intro")}</p>
      <Card className="flex flex-wrap items-center gap-3">
        <Input
          type="search"
          aria-label={t("admin.openingBalances.search")}
          placeholder={t("admin.openingBalances.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <span className="text-ink-2">{t("admin.openingBalances.count", { count: list.data?.count ?? 0 })}</span>
      </Card>
      <Card>
        {list.isPending ? (
          <p className="text-ink-2">{t("common.loading")}</p>
        ) : rows.length === 0 ? (
          <EmptyState illustration="mix" title={t("admin.openingBalances.empty")} />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.openingBalances.columns.number")}</Th>
                <Th>{t("admin.openingBalances.columns.date")}</Th>
                <Th>{t("admin.openingBalances.columns.customer")}</Th>
                <Th numeric>{t("admin.openingBalances.columns.initial")}</Th>
                <Th numeric>{t("admin.openingBalances.columns.collected")}</Th>
                <Th numeric>{t("admin.openingBalances.columns.left")}</Th>
                <Th>{t("admin.openingBalances.columns.origin")}</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <Td>
                    <Link to={`/ventes/${row.id}`} className="num font-semibold text-sea hover:underline">
                      {row.number}
                    </Link>
                    {row.status === "cancelled" && (
                      <Pill tone="bad" className="ms-2">
                        {t("admin.openingBalances.cancelled")}
                      </Pill>
                    )}
                  </Td>
                  <Td className="num">{formatDate(row.sold_at)}</Td>
                  <Td>
                    {row.customer.name}
                    <div className="num text-[0.8rem] text-ink-2">{row.customer.reference}</div>
                  </Td>
                  <Td numeric>{formatMoney(row.total)}</Td>
                  <Td numeric>{formatMoney(collected(row.total, row.amount_due))}</Td>
                  <Td numeric className="font-semibold">
                    {formatMoney(row.amount_due)}
                  </Td>
                  <Td className="text-[0.85rem] text-ink-2">{row.notes || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}

/** The page of one opening balance (OUV), in place of a delivery note's: no products, no delivery, no invoice,
 * no margin (D-283). */
export function OpeningBalanceDetail({ sale }: { sale: SaleDetail }) {
  const { t } = useTranslation();
  const rows: [string, ReactNode][] = [
    [t("admin.openingBalances.columns.customer"), `${sale.customer.name} · ${sale.customer.reference}`],
    [t("admin.openingBalances.columns.date"), <span className="num">{formatDate(sale.sold_at)}</span>],
    [t("admin.openingBalances.columns.initial"), <span className="num">{formatMoney(sale.total)}</span>],
    [
      t("admin.openingBalances.columns.collected"),
      <span className="num">{formatMoney(collected(sale.total, sale.amount_due))}</span>,
    ],
    [t("admin.openingBalances.columns.left"), <b className="num">{formatMoney(sale.amount_due)}</b>],
    [t("admin.openingBalances.columns.origin"), sale.notes || "—"],
    [
      t("admin.openingBalances.imported"),
      `${sale.created_by || "—"} · ${sale.created_at ? formatDateTime(sale.created_at) : "—"}`,
    ],
  ];
  return (
    <>
      <Link to="/tresorerie/soldes-ouverture" className="text-[0.85rem] font-semibold text-sea hover:underline">
        {t("admin.openingBalances.back")}
      </Link>
      <PageHeader eyebrow={t("admin.openingBalances.title")} title={sale.number}>
        <Pill tone={sale.status === "cancelled" ? "bad" : Number(sale.amount_due) > 0 ? "warn" : "good"}>
          {sale.status === "cancelled"
            ? t("admin.openingBalances.cancelled")
            : Number(sale.amount_due) > 0
              ? t("admin.openingBalances.open")
              : t("admin.openingBalances.settled")}
        </Pill>
      </PageHeader>
      <p role="note" className="rounded-chip bg-surface-2 px-3 py-2 text-[0.9rem]">
        {t("admin.openingBalances.note")}
      </p>
      <Card>
        <CardTitle>{t("admin.openingBalances.detail")}</CardTitle>
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-x-6 gap-y-3">
          {rows.map(([label, value]) => (
            <div key={label}>
              <dt className="text-[0.8rem] text-ink-2">{label}</dt>
              <dd className="font-semibold">{value}</dd>
            </div>
          ))}
        </dl>
        {sale.status === "confirmed" && Number(sale.amount_due) > 0 && (
          <Link
            to={`/reglements/nouveau?client=${sale.customer.id}`}
            className="mt-4 inline-block text-[0.9rem] font-semibold text-sea hover:underline"
          >
            {t("admin.openingBalances.collect")}
          </Link>
        )}
      </Card>
    </>
  );
}
