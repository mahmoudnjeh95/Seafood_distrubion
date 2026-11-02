import { type ListWebRequestsStatus, useListWebRequests } from "@frutti/api";
import { formatDateTime, useTranslation } from "@frutti/i18n";
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
  useServerTable,
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { KIND_TONE, STATUS_TONE } from "./shared";

const FILTERS = ["new", "handled", "cancelled", "all"] as const;
type Filter = (typeof FILTERS)[number];

/** Quote requests and orders sent from the public site (D-186), the new ones first. */
export function WebRequestsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("new");
  const table = useServerTable();
  const query = useDebounced(search.trim());

  const status: ListWebRequestsStatus | undefined = filter === "all" ? undefined : filter;
  const requests = useListWebRequests(
    { ...table.params, ...(status ? { status } : {}), ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = requests.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || filter !== "new";

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.sales")} title={t("admin.webRequests.title")} />

      <p className="text-ink-2">{t("admin.webRequests.intro")}</p>

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.webRequests.search")}
          placeholder={t("admin.webRequests.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div role="group" aria-label={t("admin.webRequests.show")} className="flex rounded-control bg-surface-2 p-1">
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
              {t(`admin.webRequests.filter.${choice}`)}
            </button>
          ))}
        </div>
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.webRequests.count", { count: page.count })}
        </span>
      </Card>

      {requests.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : requests.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.webRequests.noMatch")}</p>
        ) : (
          <EmptyState illustration="mix" title={t("admin.webRequests.empty")}>
            {t("admin.webRequests.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.webRequests.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.webRequests.columns.date")}
                </SortTh>
                <SortTh sortKey="customer" {...table.sorting}>
                  {t("admin.webRequests.columns.customer")}
                </SortTh>
                <SortTh sortKey="phone" {...table.sorting}>
                  {t("admin.webRequests.columns.phone")}
                </SortTh>
                <Th className="max-[720px]:hidden">{t("admin.webRequests.columns.products")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((request) => (
                <tr
                  key={request.id}
                  onClick={() => void navigate(`/demandes-site/${request.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/demandes-site/${request.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {request.number}
                    </Link>
                    <Pill className="ms-2" tone={KIND_TONE[request.kind]}>
                      {t(`admin.webRequests.kind.${request.kind}`)}
                    </Pill>
                    {filter === "all" && (
                      <Pill className="ms-2" tone={STATUS_TONE[request.status]}>
                        {t(`admin.webRequests.status.${request.status}`)}
                      </Pill>
                    )}
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDateTime(request.created_at)}</Td>
                  <Td>
                    <span className="font-semibold">{request.full_name}</span>
                    {(request.company || request.city) && (
                      <div className="text-[0.8rem] text-ink-2">
                        {[request.company, request.city].filter(Boolean).join(" · ")}
                      </div>
                    )}
                  </Td>
                  <Td className="num whitespace-nowrap">
                    <a
                      href={`tel:${request.phone.replaceAll(" ", "")}`}
                      className="text-sea hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {request.phone}
                    </a>
                  </Td>
                  <Td className="max-[720px]:hidden">
                    {request.lines.length > 0
                      ? t("admin.webRequests.productsCount", { count: request.lines.length })
                      : "—"}
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
