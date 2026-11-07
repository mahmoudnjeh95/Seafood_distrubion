import { type ListPriceRequestsStatus, useListPriceRequests } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, useTranslation } from "@frutti/i18n";
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
  Table,
  Td,
  Th,
  useServerTable,
  useUrlState,
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { PurchasingTabs } from "../purchasing/PurchasingTabs";
import { canRecordReceipts } from "../receipts/shared";
import { REQUEST_TONE } from "./shared";

const FILTERS = ["open", "ordered", "all"] as const;
type Filter = (typeof FILTERS)[number];

/** "Demandes de prix" (D-289): products and kilos asked to several suppliers, to compare their offers. */
export function PriceRequestsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canRecord = canRecordReceipts(session);
  const [search, setSearch] = useUrlState("q");
  const [filter, setFilter] = useState<Filter>("open");
  const table = useServerTable();
  const query = useDebounced(search.trim());

  const status: ListPriceRequestsStatus | undefined = filter === "all" ? undefined : filter;
  const requests = useListPriceRequests(
    { ...table.params, ...(status ? { status } : {}), ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = requests.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || filter !== "open";

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.priceRequests.title")}>
        {canRecord && (
          <Button variant="primary" onClick={() => void navigate("/achats/demandes/nouvelle")}>
            <Icon name="plus" />
            {t("admin.priceRequests.add")}
          </Button>
        )}
      </PageHeader>

      <PurchasingTabs />

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.priceRequests.search")}
          placeholder={t("admin.priceRequests.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div role="group" aria-label={t("admin.priceRequests.show")} className="flex rounded-control bg-surface-2 p-1">
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
              {t(`admin.priceRequests.filter.${choice}`)}
            </button>
          ))}
        </div>
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.priceRequests.count", { count: page.count })}
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
          <p className="text-ink-2">{t("admin.priceRequests.noMatch")}</p>
        ) : (
          <EmptyState illustration="fish" title={t("admin.priceRequests.empty")}>
            {t("admin.priceRequests.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.priceRequests.columns.number")}</Th>
                <Th>{t("admin.priceRequests.columns.date")}</Th>
                <Th>{t("admin.priceRequests.columns.products")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.priceRequests.columns.suppliers")}</Th>
                <Th numeric>{t("admin.priceRequests.columns.answers")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((request) => (
                <tr
                  key={request.id}
                  onClick={() => void navigate(`/achats/demandes/${request.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/achats/demandes/${request.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {request.number}
                    </Link>
                    <Pill className="ms-2" tone={REQUEST_TONE[request.status]}>
                      {t(`admin.priceRequests.status.${request.status}`)}
                    </Pill>
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(request.requested_on)}</Td>
                  <Td>{request.lines.map((line) => line.product.name).join(", ")}</Td>
                  <Td className="max-[720px]:hidden">
                    {request.offers.map((offer) => offer.supplier.name).join(", ")}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {t("admin.priceRequests.answers", {
                      answered: request.offers.filter((offer) => offer.lines.length > 0).length,
                      asked: request.offers.length,
                    })}
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
