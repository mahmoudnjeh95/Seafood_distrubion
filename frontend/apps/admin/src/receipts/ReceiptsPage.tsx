import { useListReceipts } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
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
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { PurchasingTabs } from "../purchasing/PurchasingTabs";
import { canRecordReceipts } from "./shared";

export function ReceiptsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canRecord = canRecordReceipts(session);
  const differencesId = useId();
  const [search, setSearch] = useState("");
  const [onlyDifferences, setOnlyDifferences] = useState(false);
  const table = useServerTable();
  const query = useDebounced(search.trim());

  const receipts = useListReceipts(
    { ...table.params, differences: onlyDifferences, ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = receipts.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || onlyDifferences;

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.receipts.title")}>
        {canRecord && (
          <Button variant="primary" onClick={() => void navigate("/achats/nouvelle")}>
            <Icon name="plus" />
            {t("admin.receipts.add")}
          </Button>
        )}
      </PageHeader>

      <PurchasingTabs />

      {!canRecord && <p className="text-ink-2">{t("admin.receipts.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.receipts.search")}
          placeholder={t("admin.receipts.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <label htmlFor={differencesId} className="flex items-center gap-2 text-[0.9rem]">
          <input
            id={differencesId}
            type="checkbox"
            checked={onlyDifferences}
            onChange={(event) => {
              setOnlyDifferences(event.target.checked);
              table.backToFirstPage();
            }}
            className="size-4 accent-coral"
          />
          {t("admin.receipts.onlyDifferences")}
        </label>
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.receipts.count", { count: page.count })}
        </span>
      </Card>

      {receipts.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : receipts.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.receipts.noMatch")}</p>
        ) : (
          <EmptyState illustration="fish" title={t("admin.receipts.empty")}>
            {t("admin.receipts.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.receipts.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.receipts.columns.date")}
                </SortTh>
                <SortTh sortKey="supplier" {...table.sorting}>
                  {t("admin.receipts.columns.supplier")}
                </SortTh>
                <Th className="max-[720px]:hidden">{t("admin.receipts.columns.location")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.receipts.columns.lines")}</Th>
                <Th numeric>{t("admin.receipts.columns.invoiced")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((receipt) => (
                // The number is the link; a click anywhere on the row opens the same page.
                <tr
                  key={receipt.id}
                  onClick={() => void navigate(`/achats/${receipt.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/achats/${receipt.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {receipt.number}
                    </Link>
                    {receipt.has_differences && (
                      <Pill className="ms-2" tone="warn">
                        {t("admin.receipts.difference")}
                      </Pill>
                    )}
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(receipt.received_on)}</Td>
                  <Td>
                    <span className="font-semibold">{receipt.supplier.name}</span>
                    {receipt.supplier_reference && (
                      <div className="num text-[0.8rem] text-ink-2">{receipt.supplier_reference}</div>
                    )}
                  </Td>
                  <Td className="max-[720px]:hidden">{receipt.location.name}</Td>
                  <Td className="text-ink-2 max-[720px]:hidden">
                    {t("admin.receipts.linesCount", { count: receipt.lines.length })}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatMoney(receipt.invoiced_total)}
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
