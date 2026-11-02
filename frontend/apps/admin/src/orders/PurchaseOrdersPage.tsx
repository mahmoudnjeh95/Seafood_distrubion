import { type ListPurchaseOrdersStatus, useListPurchaseOrders } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  cn,
  EmptyState,
  Icon,
  Input,
  PageHeader,
  Pager,
  Pill,
  SortTh,
  Table,
  Td,
  Th,
  useServerTable,
  useUrlState,
} from "@frutti/ui";
import { useState } from "react";
import { keepPreviousData } from "@tanstack/react-query";

import { Link, useNavigate, useOutletContext } from "react-router";

import { sum } from "../lib/decimal";
import { useDebounced } from "../lib/useDebounced";
import { PurchasingTabs } from "../purchasing/PurchasingTabs";
import { canRecordReceipts } from "../receipts/shared";
import { ORDER_TONE } from "./shared";

const FILTERS = ["pending", "received", "closed", "all"] as const;
type Filter = (typeof FILTERS)[number];

export function PurchaseOrdersPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canRecord = canRecordReceipts(session);
  const [search, setSearch] = useUrlState("q");
  const [filter, setFilter] = useState<Filter>("pending");
  const table = useServerTable();
  const query = useDebounced(search.trim());

  const status: ListPurchaseOrdersStatus | undefined = filter === "all" ? undefined : filter;
  const orders = useListPurchaseOrders(
    { ...table.params, ...(status ? { status } : {}), ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = orders.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || filter !== "pending";

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.purchaseOrders.title")}>
        {canRecord && (
          <Button variant="primary" onClick={() => void navigate("/achats/bons/nouveau")}>
            <Icon name="plus" />
            {t("admin.purchaseOrders.add")}
          </Button>
        )}
      </PageHeader>

      <PurchasingTabs />

      {!canRecord && <p className="text-ink-2">{t("admin.purchaseOrders.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.purchaseOrders.search")}
          placeholder={t("admin.purchaseOrders.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div role="group" aria-label={t("admin.purchaseOrders.show")} className="flex rounded-control bg-surface-2 p-1">
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
              {t(`admin.purchaseOrders.filter.${choice}`)}
            </button>
          ))}
        </div>
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.purchaseOrders.count", { count: page.count })}
        </span>
      </Card>

      {orders.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : orders.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.purchaseOrders.noMatch")}</p>
        ) : (
          <EmptyState illustration="fish" title={t("admin.purchaseOrders.empty")}>
            {t("admin.purchaseOrders.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.purchaseOrders.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.purchaseOrders.columns.date")}
                </SortTh>
                <SortTh sortKey="supplier" {...table.sorting}>
                  {t("admin.purchaseOrders.columns.supplier")}
                </SortTh>
                <Th className="max-[720px]:hidden">{t("admin.purchaseOrders.columns.expected")}</Th>
                <Th numeric>{t("admin.purchaseOrders.columns.progress")}</Th>
                <Th numeric className="max-[720px]:hidden">
                  {t("admin.purchaseOrders.columns.total")}
                </Th>
              </tr>
            </thead>
            <tbody>
              {list.map((order) => (
                // The number is the link; a click anywhere on the row opens the same page.
                <tr
                  key={order.id}
                  onClick={() => void navigate(`/achats/bons/${order.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/achats/bons/${order.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {order.number}
                    </Link>
                    <Pill className="ms-2" tone={ORDER_TONE[order.status]}>
                      {t(`admin.purchaseOrders.status.${order.status}`)}
                    </Pill>
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(order.ordered_on)}</Td>
                  <Td className="font-semibold">{order.supplier.name}</Td>
                  <Td className="num whitespace-nowrap max-[720px]:hidden">
                    {order.expected_on ? formatDate(order.expected_on) : t("admin.purchaseOrders.detail.none")}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {t("admin.purchaseOrders.progress", {
                      received: formatQuantity(sum(order.lines.map((line) => line.received_quantity))),
                      ordered: formatQuantity(sum(order.lines.map((line) => line.ordered_quantity))),
                    })}
                  </Td>
                  <Td numeric className="whitespace-nowrap max-[720px]:hidden">
                    {formatMoney(order.ordered_total)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      )}
    </>
  );
}
