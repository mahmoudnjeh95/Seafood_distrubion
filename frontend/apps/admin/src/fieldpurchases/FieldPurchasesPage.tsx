import { type ListFieldPurchasesStatus, useListFieldPurchases } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, cn, EmptyState, Icon, Input, PageHeader, Pager, Pill, SortTh, Table, Td, Th, TotalsRow, useServerTable } from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { PurchasingTabs } from "../purchasing/PurchasingTabs";
import { useDebounced } from "../lib/useDebounced";
import { totalOf } from "../lib/totals";
import { canRecordReceipts } from "../receipts/shared";
import { STATUS_TONE } from "./shared";

const FILTERS = ["submitted", "validated", "refused", "all"] as const;
type Filter = (typeof FILTERS)[number];

/** What drivers bought at the port, the ones to check first. */
export function FieldPurchasesPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canRecord = canRecordReceipts(session);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("submitted");
  const table = useServerTable();
  const query = useDebounced(search.trim());

  const status: ListFieldPurchasesStatus | undefined = filter === "all" ? undefined : filter;
  const purchases = useListFieldPurchases(
    { ...table.params, ...(status ? { status } : {}), ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = purchases.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || filter !== "submitted";

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.fieldPurchases.title")}>
        {canRecord && (
          <Button variant="primary" onClick={() => void navigate("/achats/terrain/nouveau")}>
            <Icon name="plus" />
            {t("admin.fieldPurchases.add")}
          </Button>
        )}
      </PageHeader>

      <PurchasingTabs />

      <p className="text-ink-2">{canRecord ? t("admin.fieldPurchases.intro") : t("admin.fieldPurchases.readOnly")}</p>

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.fieldPurchases.search")}
          placeholder={t("admin.fieldPurchases.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div role="group" aria-label={t("admin.fieldPurchases.show")} className="flex rounded-control bg-surface-2 p-1">
          {FILTERS.map((choice) => (
            <button
              key={choice}
              type="button"
              aria-pressed={filter === choice}
              onClick={() => {
                setFilter(choice);
                table.backToFirstPage();
              }}
              className={cn(
                "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
                filter === choice && "bg-surface text-ink shadow-card",
              )}
            >
              {t(`admin.fieldPurchases.filter.${choice}`)}
            </button>
          ))}
        </div>
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.fieldPurchases.count", { count: page.count })}
        </span>
      </Card>

      {purchases.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : purchases.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.fieldPurchases.noMatch")}</p>
        ) : (
          <EmptyState illustration="fish" title={t("admin.fieldPurchases.empty")}>
            {t("admin.fieldPurchases.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.fieldPurchases.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.fieldPurchases.columns.date")}
                </SortTh>
                <SortTh sortKey="supplier" {...table.sorting}>
                  {t("admin.fieldPurchases.columns.supplier")}
                </SortTh>
                <Th className="max-[720px]:hidden">{t("admin.fieldPurchases.columns.buyer")}</Th>
                <Th numeric>{t("admin.fieldPurchases.columns.total")}</Th>
                <Th numeric className="max-[720px]:hidden">
                  {t("admin.fieldPurchases.columns.paid")}
                </Th>
                <Th numeric>{t("admin.fieldPurchases.columns.rest")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((purchase) => (
                // The number is the link; a click anywhere on the row opens the same page.
                <tr
                  key={purchase.id}
                  onClick={() => void navigate(`/achats/terrain/${purchase.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/achats/terrain/${purchase.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {purchase.number}
                    </Link>
                    <Pill className="ms-2" tone={STATUS_TONE[purchase.status]}>
                      {t(`admin.fieldPurchases.status.${purchase.status}`)}
                    </Pill>
                    {purchase.is_late && (
                      <Pill className="ms-2" tone="bad" title={t("admin.fieldPurchases.late")}>
                        {t("admin.fieldPurchases.lateShort")}
                      </Pill>
                    )}
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(purchase.bought_on)}</Td>
                  <Td>
                    <span className="font-semibold">{purchase.supplier?.name ?? purchase.proposed_supplier}</span>
                    {!purchase.supplier && (
                      <Pill className="ms-2" tone="warn">
                        {t("admin.fieldPurchases.newName")}
                      </Pill>
                    )}
                    {purchase.supplier_reference && (
                      <div className="num text-[0.8rem] text-ink-2">{purchase.supplier_reference}</div>
                    )}
                  </Td>
                  <Td className="max-[720px]:hidden">{purchase.buyer}</Td>
                  <Td numeric className="font-semibold whitespace-nowrap">
                    {formatMoney(purchase.total)}
                  </Td>
                  <Td numeric className="whitespace-nowrap max-[720px]:hidden">
                    {formatMoney(purchase.paid)}
                  </Td>
                  <Td numeric className="font-semibold whitespace-nowrap">
                    {formatMoney(purchase.rest)}
                  </Td>
                </tr>
              ))}
            </tbody>
              <TotalsRow span={4} cells={[{ value: totalOf(list.filter((p) => p.status !== "refused"), (p) => p.total) }, { value: totalOf(list.filter((p) => p.status !== "refused"), (p) => p.paid), phoneHidden: true }, { value: totalOf(list.filter((p) => p.status !== "refused"), (p) => p.rest) }]} />
          </Table>
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      )}
    </>
  );
}
