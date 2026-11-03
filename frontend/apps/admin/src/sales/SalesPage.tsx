import {
  getExportSalesUrl,
  createInvoice,
  type DeliveryStatusEnum,
  type SaleStatusEnum,
  useListSales,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDateTime, formatMoney, useTranslation } from "@frutti/i18n";
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
  toast,
  TotalsRow,
  useServerTable,
  useUrlState,
} from "@frutti/ui";
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { totalOf } from "../lib/totals";
import { fieldErrors } from "../lib/errors";
import { useDebounced } from "../lib/useDebounced";
import { canSell, DELIVERY_TONES, SALE_STATUSES, STATUS_TONES } from "./shared";
import { ExportButton } from "../lib/ExportButton";

// The BL of the truck loads by where their delivery stands (D-178).
const DELIVERY_FILTERS: DeliveryStatusEnum[] = ["to_deliver", "partial", "delivered", "cancelled"];

const isZero = (value: string) => /^0+(\.0+)?$/.test(value);

/** "Ventes": every sale, newest first, with what the customer still owes on it. */
export function SalesPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canWrite = canSell(session);
  const [search, setSearch] = useUrlState("q");
  const [status, setStatus] = useState<SaleStatusEnum | "">("");
  const [delivery, setDelivery] = useState<DeliveryStatusEnum | "">("");
  const table = useServerTable();
  // "À facturer": the BL still to invoice, which can be ticked to make one invoice (D-096).
  const [uninvoiced, setUninvoiced] = useState(false);
  const [chosen, setChosen] = useState<Record<number, number>>({});
  const query = useDebounced(search.trim());
  const queryClient = useQueryClient();

  const filters = {
    ...(status ? { status } : {}),
    ...(delivery ? { delivery_status: delivery } : {}),
    ...(query ? { search: query } : {}),
    ...(uninvoiced ? { uninvoiced: true } : {}),
  };
  const sales = useListSales({ ...table.params, ...filters }, { query: { placeholderData: keepPreviousData } });
  const page = sales.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || status !== "" || delivery !== "" || uninvoiced;
  const chosenIds = Object.keys(chosen).map(Number);

  const groupInvoice = useMutation({
    mutationFn: () => createInvoice({ sales: chosenIds }),
    onSuccess: async (saved) => {
      toast.success(t("admin.sales.groupInvoice.ready", { count: chosenIds.length }));
      await queryClient.invalidateQueries();
      void navigate(`/factures/${saved.id}`);
    },
    onError: (failure) => {
      toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.sales.groupInvoice.failed"));
    },
  });
  const startGroupInvoice = () => {
    if (new Set(Object.values(chosen)).size > 1) toast.error(t("admin.sales.groupInvoice.mixed"));
    else groupInvoice.mutate();
  };

  const statusButton = (value: SaleStatusEnum | "", label: string) => (
    <button
      key={value || "all"}
      type="button"
      aria-pressed={status === value}
      onClick={() => {
        setStatus(value);
        table.backToFirstPage();
      }}
      className={cn(
        "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
        status === value && "bg-surface text-ink shadow-card",
      )}
    >
      {label}
    </button>
  );

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.sales")} title={t("admin.sales.title")}>
        {canWrite && (
          <>
            <Button onClick={() => void navigate("/ventes/nouvelle")}>
              <Icon name="plus" />
              {t("admin.sales.add")}
            </Button>
            <Button variant="primary" onClick={() => void navigate("/ventes/comptoir")}>
              <Icon name="cash" />
              {t("admin.sales.counter")}
            </Button>
          </>
        )}
        <ExportButton href={getExportSalesUrl({ ...table.ordering, ...filters })} />
      </PageHeader>

      {!canWrite && <p className="text-ink-2">{t("admin.sales.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.sales.search")}
          placeholder={t("admin.sales.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div
          role="group"
          aria-label={t("admin.sales.statusFilter")}
          className="flex flex-wrap rounded-control bg-surface-2 p-1"
        >
          {statusButton("", t("admin.sales.allStatuses"))}
          {SALE_STATUSES.map((value) => statusButton(value, t(`admin.sales.statuses.${value}`)))}
        </div>
        <div
          role="group"
          aria-label={t("admin.sales.deliveryFilter")}
          className="flex flex-wrap rounded-control bg-surface-2 p-1"
        >
          {(["", ...DELIVERY_FILTERS] as const).map((value) => (
            <button
              key={value || "all"}
              type="button"
              aria-pressed={delivery === value}
              onClick={() => {
                setDelivery(value);
                table.backToFirstPage();
              }}
              className={cn(
                "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
                delivery === value && "bg-surface text-ink shadow-card",
              )}
            >
              {value ? t(`admin.sales.deliveryStatuses.${value}`) : t("admin.sales.allDeliveries")}
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-pressed={uninvoiced}
          onClick={() => {
            setUninvoiced(!uninvoiced);
            setChosen({});
            table.backToFirstPage();
          }}
          className={cn(
            "rounded-control border border-line px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
            uninvoiced && "bg-surface text-ink shadow-card",
          )}
        >
          {t("admin.sales.groupInvoice.filter")}
        </button>
        {canWrite && uninvoiced && chosenIds.length > 0 && (
          <Button variant="primary" disabled={groupInvoice.isPending} onClick={startGroupInvoice}>
            <Icon name="receipt" />
            {t("admin.sales.groupInvoice.action", { count: chosenIds.length })}
          </Button>
        )}
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.sales.count", { count: page.count })}
        </span>
      </Card>

      {sales.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : sales.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.sales.noMatch")}</p>
        ) : (
          <EmptyState illustration="truck" title={t("admin.sales.empty")}>
            {t("admin.sales.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                {canWrite && uninvoiced && <Th>{null}</Th>}
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.sales.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.sales.columns.date")}
                </SortTh>
                <SortTh sortKey="customer" {...table.sorting}>
                  {t("admin.sales.columns.customer")}
                </SortTh>
                <Th numeric>{t("admin.sales.columns.total")}</Th>
                <Th numeric className="max-[720px]:hidden">
                  {t("admin.sales.columns.due")}
                </Th>
              </tr>
            </thead>
            <tbody>
              {list.map((sale) => (
                // The number is the link; a click anywhere on the row opens the same page.
                <tr
                  key={sale.id}
                  onClick={() => void navigate(`/ventes/${sale.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  {canWrite && uninvoiced && (
                    <Td onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={t("admin.sales.groupInvoice.select", { number: sale.number })}
                        checked={sale.id in chosen}
                        onChange={(event) => {
                          const next = { ...chosen };
                          if (event.target.checked) next[sale.id] = sale.customer.id;
                          else delete next[sale.id];
                          setChosen(next);
                        }}
                      />
                    </Td>
                  )}
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/ventes/${sale.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {sale.number}
                    </Link>
                    {sale.delivery_status ? (
                      <Pill className="ms-2" tone={DELIVERY_TONES[sale.delivery_status]}>
                        {t(`admin.sales.deliveryStatuses.${sale.delivery_status}`)}
                      </Pill>
                    ) : (
                      <Pill className="ms-2" tone={STATUS_TONES[sale.status]}>
                        {t(`admin.sales.statuses.${sale.status}`)}
                      </Pill>
                    )}
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDateTime(sale.sold_at)}</Td>
                  <Td>
                    <span className="font-semibold">{sale.customer.name}</span>
                    <div className="num text-[0.8rem] text-ink-2">{sale.customer.reference}</div>
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatMoney(sale.total_excl_tax)}
                  </Td>
                  <Td
                    numeric
                    className={cn(
                      "whitespace-nowrap max-[720px]:hidden",
                      sale.status === "confirmed" && !isZero(sale.amount_due) && "font-semibold text-warn",
                    )}
                  >
                    {sale.status === "confirmed" ? formatMoney(sale.amount_due) : "—"}
                  </Td>
                </tr>
              ))}
            </tbody>
            <TotalsRow
              span={(canWrite && uninvoiced ? 1 : 0) + 3}
              cells={[
                {
                  value: totalOf(
                    list.filter((s) => s.status !== "cancelled"),
                    (s) => s.total_excl_tax,
                  ),
                },
                {
                  value: totalOf(
                    list.filter((s) => s.status === "confirmed"),
                    (s) => s.amount_due,
                  ),
                  phoneHidden: true,
                },
              ]}
            />
          </Table>
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      )}
    </>
  );
}
