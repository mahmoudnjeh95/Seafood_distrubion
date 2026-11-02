import { type QuoteStatusEnum, useListQuotes } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
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
  TotalsRow,
  useServerTable,
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { totalOf } from "../lib/totals";
import { canWriteQuotes, QUOTE_STATUSES, STATUS_TONES } from "./shared";

/** "Devis": every quote, newest first, with its status as the customer sees it today. */
export function QuotesPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canWrite = canWriteQuotes(session);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<QuoteStatusEnum | "">("");
  const table = useServerTable();
  const query = useDebounced(search.trim());

  const quotes = useListQuotes(
    { ...table.params, ...(status ? { status } : {}), ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = quotes.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || status !== "";

  const statusButton = (value: QuoteStatusEnum | "", label: string) => (
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
      <PageHeader eyebrow={t("admin.groups.sales")} title={t("admin.quotes.title")}>
        {canWrite && (
          <Button variant="primary" onClick={() => void navigate("/devis/nouveau")}>
            <Icon name="plus" />
            {t("admin.quotes.add")}
          </Button>
        )}
      </PageHeader>

      {!canWrite && <p className="text-ink-2">{t("admin.quotes.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.quotes.search")}
          placeholder={t("admin.quotes.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div
          role="group"
          aria-label={t("admin.quotes.statusFilter")}
          className="flex flex-wrap rounded-control bg-surface-2 p-1"
        >
          {statusButton("", t("admin.quotes.allStatuses"))}
          {QUOTE_STATUSES.map((value) => statusButton(value, t(`admin.quotes.statuses.${value}`)))}
        </div>
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.quotes.count", { count: page.count })}
        </span>
      </Card>

      {quotes.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : quotes.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.quotes.noMatch")}</p>
        ) : (
          <EmptyState illustration="mix" title={t("admin.quotes.empty")}>
            {t("admin.quotes.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.quotes.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.quotes.columns.date")}
                </SortTh>
                <SortTh sortKey="customer" {...table.sorting}>
                  {t("admin.quotes.columns.customer")}
                </SortTh>
                <Th className="max-[720px]:hidden">{t("admin.quotes.columns.validUntil")}</Th>
                <Th numeric>{t("admin.quotes.columns.total")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((quote) => (
                // The number is the link; a click anywhere on the row opens the same page.
                <tr
                  key={quote.id}
                  onClick={() => void navigate(`/devis/${quote.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/devis/${quote.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {quote.number}
                    </Link>
                    <Pill className="ms-2" tone={STATUS_TONES[quote.status]}>
                      {t(`admin.quotes.statuses.${quote.status}`)}
                    </Pill>
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(quote.quoted_on)}</Td>
                  <Td>
                    <span className="font-semibold">{quote.customer.name}</span>
                    <div className="num text-[0.8rem] text-ink-2">{quote.customer.reference}</div>
                  </Td>
                  <Td className="num whitespace-nowrap max-[720px]:hidden">{formatDate(quote.valid_until)}</Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatMoney(quote.total_excl_tax)}
                  </Td>
                </tr>
              ))}
            </tbody>
            <TotalsRow span={4} cells={[{ value: totalOf(list, (q) => q.total_excl_tax) }]} />
          </Table>
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      )}
    </>
  );
}
