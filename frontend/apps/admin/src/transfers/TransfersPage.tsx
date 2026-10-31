import { type TransferKindEnum, useListTransfers } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, cn, EmptyState, Icon, Input, PageHeader, Pill, Table, Td, Th } from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { canRecordTransfers, KIND_ICONS, STATUS_TONES } from "./shared";

const PAGE_SIZE = 50;
const KINDS: TransferKindEnum[] = ["load", "return", "internal"];

export function TransfersPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canRecord = canRecordTransfers(session);
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<TransferKindEnum | "">("");
  const [offset, setOffset] = useState(0);
  const query = useDebounced(search.trim());

  const transfers = useListTransfers(
    { limit: PAGE_SIZE, offset, ...(kind ? { kind } : {}), ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = transfers.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || kind !== "";

  const kindButton = (value: TransferKindEnum | "", label: string) => (
    <button
      key={value || "all"}
      type="button"
      aria-pressed={kind === value}
      onClick={() => {
        setKind(value);
        setOffset(0);
      }}
      className={cn(
        "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
        kind === value && "bg-surface text-ink shadow-card",
      )}
    >
      {label}
    </button>
  );

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.goods")} title={t("admin.transfers.title")}>
        {canRecord && (
          <Button variant="primary" onClick={() => void navigate("/stock/transferts/nouveau")}>
            <Icon name="plus" />
            {t("admin.transfers.add")}
          </Button>
        )}
      </PageHeader>

      {!canRecord && <p className="text-ink-2">{t("admin.transfers.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.transfers.search")}
          placeholder={t("admin.transfers.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div
          role="group"
          aria-label={t("admin.transfers.kindFilter")}
          className="flex rounded-control bg-surface-2 p-1"
        >
          {kindButton("", t("admin.transfers.allKinds"))}
          {KINDS.map((value) => kindButton(value, t(`admin.transfers.kinds.${value}`)))}
        </div>
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.transfers.count", { count: page.count })}
        </span>
      </Card>

      {transfers.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : transfers.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.transfers.noMatch")}</p>
        ) : (
          <EmptyState illustration="truck" title={t("admin.transfers.empty")}>
            {t("admin.transfers.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.transfers.columns.number")}</Th>
                <Th>{t("admin.transfers.columns.date")}</Th>
                <Th>{t("admin.transfers.columns.kind")}</Th>
                <Th>{t("admin.transfers.columns.route")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.transfers.columns.lines")}</Th>
                <Th numeric>{t("admin.transfers.columns.quantity")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((transfer) => (
                // The number is the link; a click anywhere on the row opens the same page.
                <tr
                  key={transfer.id}
                  onClick={() => void navigate(`/stock/transferts/${transfer.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/stock/transferts/${transfer.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {transfer.number}
                    </Link>
                    <Pill className="ms-2" tone={STATUS_TONES[transfer.status]}>
                      {t(`admin.transfers.statuses.${transfer.status}`)}
                    </Pill>
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(transfer.transferred_on)}</Td>
                  <Td className="whitespace-nowrap">
                    <span className="inline-flex items-center gap-1.5">
                      <Icon name={KIND_ICONS[transfer.kind]} />
                      {t(`admin.transfers.kinds.${transfer.kind}`)}
                    </span>
                  </Td>
                  <Td>
                    {t("admin.transfers.route", {
                      from: transfer.from_cold_rooms ? t("admin.transfers.coldRooms") : transfer.from_location.name,
                      to: transfer.to_location.name,
                    })}
                  </Td>
                  <Td className="whitespace-nowrap text-ink-2 max-[720px]:hidden">
                    {t("admin.transfers.linesCount", { count: transfer.lines.length })}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatQuantity(transfer.total_quantity)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {page && page.count > PAGE_SIZE && (
            <div className="flex items-center justify-end gap-2 p-2">
              <span className="me-auto text-[0.85rem] text-ink-2">
                {t("admin.transfers.page", {
                  from: offset + 1,
                  to: Math.min(offset + PAGE_SIZE, page.count),
                  count: page.count,
                })}
              </span>
              <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                {t("admin.transfers.previous")}
              </Button>
              <Button disabled={!page.next} onClick={() => setOffset(offset + PAGE_SIZE)}>
                {t("admin.transfers.next")}
              </Button>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
