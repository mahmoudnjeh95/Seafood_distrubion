import { type BoxMovement, type BoxTypeEnum, useListBoxBalances, useListBoxMovements } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  cn,
  Dialog,
  EmptyState,
  Icon,
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
import { useMemo, useState } from "react";
import { useNavigate, useOutletContext } from "react-router";

import { StockTabs } from "../lib/StockTabs";
import { canRecordReceipts } from "../receipts/shared";
import { canRecordTransfers } from "../transfers/shared";
import { BoxAdjustDialog } from "./BoxAdjustDialog";
import {
  BOX_TYPES,
  type HolderCounts,
  type HolderKind,
  HOLDER_KINDS,
  boxSummary,
  formatBoxCount,
  holdersFromBalances,
  holdersOfKind,
} from "./shared";

const SELECT_CLASSES = "rounded-control border border-line bg-surface px-3 py-2 text-ink";
const LABEL_CLASSES = "flex flex-col gap-1 text-[0.78rem] font-semibold text-ink-2";
const KIND_TONES = {
  opening: "good",
  receive: "good",
  load: "sea",
  leave: "coral",
  collect: "neutral",
  return: "neutral",
  truck_return: "sea",
  write_off: "bad",
  purchase: "good",
} as const;
const SUMMARY_COLUMNS = ["inHand", "atCustomers", "owedToSuppliers"] as const;

/** The returnable boxes (caisses): what each holder has now, and the history of moves (P1-T14). Read only. */
export function BoxesPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const balances = useListBoxBalances();
  const holders = useMemo(() => holdersFromBalances(balances.data ?? []), [balances.data]);
  // Boxes come in with a receipt or a load: the places to record them, for whoever may record them.
  const canRecord = canRecordReceipts(session) || canRecordTransfers(session);
  const [adjusting, setAdjusting] = useState(false);

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.goods")} title={t("admin.boxes.title")} />
      <StockTabs />
      <p className="text-ink-2">{t("admin.boxes.intro")}</p>
      {canRecord && (
        <div>
          <Button onClick={() => setAdjusting(true)}>
            <Icon name="plus" />
            {t("admin.boxes.adjust.open")}
          </Button>
        </div>
      )}
      <Dialog open={adjusting} onOpenChange={setAdjusting}>
        {adjusting && <BoxAdjustDialog onDone={() => setAdjusting(false)} />}
      </Dialog>

      {balances.data?.length === 0 && (
        <Card className="mt-4 flex flex-col items-start gap-3" data-testid="boxes-empty">
          <p className="text-ink-2">{t("admin.boxes.empty.text")}</p>
          {canRecord && (
            <div className="flex flex-wrap gap-2">
              {canRecordReceipts(session) && (
                <Button variant="primary" onClick={() => void navigate("/achats/nouvelle")}>
                  <Icon name="plus" />
                  {t("admin.boxes.empty.receipt")}
                </Button>
              )}
              {canRecordTransfers(session) && (
                <Button onClick={() => void navigate("/stock/transferts/nouveau")}>
                  <Icon name="truck" />
                  {t("admin.boxes.empty.load")}
                </Button>
              )}
            </div>
          )}
        </Card>
      )}

      {balances.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : balances.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : (
        <>
          {holders.length > 0 && <SummaryCard holders={holders} />}
          <div className="grid items-start gap-4 min-[960px]:grid-cols-3">
            {HOLDER_KINDS.map((kind) => (
              <BalanceTable key={kind} kind={kind} holders={holdersOfKind(holders, kind)} />
            ))}
          </div>
        </>
      )}

      <BoxHistory holders={holders} />
    </>
  );
}

/** Whose boxes are whose, from the three lists below: ours, to collect from clients, to give back to suppliers (D-187). */
function SummaryCard({ holders }: { holders: HolderCounts[] }) {
  const { t } = useTranslation();
  const summary = boxSummary(holders);
  return (
    <Card className="min-w-0" data-testid="boxes-summary">
      <CardTitle>{t("admin.boxes.summary.title")}</CardTitle>
      <p className="mb-3 text-[0.85rem] text-ink-2">{t("admin.boxes.summary.hint")}</p>
      <Table>
        <thead>
          <tr>
            <Th>{t("admin.boxes.summary.boxType")}</Th>
            {SUMMARY_COLUMNS.map((column) => (
              <Th key={column} numeric>
                {t(`admin.boxes.summary.${column}`)}
              </Th>
            ))}
            <Th numeric>{t("admin.boxes.summary.own")}</Th>
          </tr>
        </thead>
        <tbody>
          {BOX_TYPES.map((boxType) => (
            <tr key={boxType}>
              <Td className="font-semibold">{t(`admin.boxes.types.${boxType}`)}</Td>
              {SUMMARY_COLUMNS.map((column) => (
                <Td key={column} numeric>
                  {formatBoxCount(summary[boxType][column])}
                </Td>
              ))}
              <Td numeric className={cn("font-bold", summary[boxType].own < 0 && "text-bad")}>
                {formatBoxCount(summary[boxType].own)}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

function BalanceTable({ kind, holders }: { kind: HolderKind; holders: HolderCounts[] }) {
  const { t } = useTranslation();
  return (
    <Card className="min-w-0">
      <CardTitle>{t(`admin.boxes.kinds.${kind}`)}</CardTitle>
      <p className="mb-3 text-[0.85rem] text-ink-2">{t(`admin.boxes.kindNotes.${kind}`)}</p>
      {holders.length === 0 ? (
        <p className="text-ink-2">{t("admin.boxes.noHolders")}</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.boxes.columns.holder")}</Th>
              <Th numeric>{t("admin.boxes.types.small")}</Th>
              <Th numeric>{t("admin.boxes.types.big")}</Th>
            </tr>
          </thead>
          <tbody>
            {holders.map((holder) => (
              <tr key={holder.id}>
                <Td className="font-semibold">{holder.name || t("admin.boxes.unnamed")}</Td>
                <Td numeric className="num">
                  {formatBoxCount(holder.small)}
                </Td>
                <Td numeric className="num">
                  {formatBoxCount(holder.big)}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

function BoxHistory({ holders }: { holders: HolderCounts[] }) {
  const { t } = useTranslation();
  const [holder, setHolder] = useState("");
  const [boxType, setBoxType] = useState<BoxTypeEnum | "">("");
  const table = useServerTable();

  const movements = useListBoxMovements(
    {
      ...table.params,
      ...(holder ? { holder: Number(holder) } : {}),
      ...(boxType ? { box_type: boxType } : {}),
    },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = movements.data;
  const list = page?.results ?? [];
  const filtering = holder !== "" || boxType !== "";

  const reset = () => {
    setHolder("");
    setBoxType("");
    table.backToFirstPage();
  };

  return (
    <section className="mt-6 flex flex-col gap-4">
      <CardTitle className="mb-0">{t("admin.boxes.history.title")}</CardTitle>

      <Card className="filter-bar flex flex-wrap items-end gap-3 p-3">
        <label className={LABEL_CLASSES}>
          {t("admin.boxes.history.holder")}
          <select
            className={SELECT_CLASSES}
            value={holder}
            onChange={(event) => {
              setHolder(event.target.value);
              table.backToFirstPage();
            }}
          >
            <option value="">{t("admin.boxes.history.allHolders")}</option>
            {holders.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name || t("admin.boxes.unnamed")}
              </option>
            ))}
          </select>
        </label>
        <label className={LABEL_CLASSES}>
          {t("admin.boxes.history.boxType")}
          <select
            className={SELECT_CLASSES}
            value={boxType}
            onChange={(event) => {
              setBoxType(event.target.value as BoxTypeEnum | "");
              table.backToFirstPage();
            }}
          >
            <option value="">{t("admin.boxes.history.allBoxTypes")}</option>
            {BOX_TYPES.map((value) => (
              <option key={value} value={value}>
                {t(`admin.boxes.types.${value}`)}
              </option>
            ))}
          </select>
        </label>
        {filtering && <Button onClick={reset}>{t("admin.boxes.history.reset")}</Button>}
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.boxes.history.count", { count: page.count })}
        </span>
      </Card>

      {movements.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : movements.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.boxes.history.noMatch")}</p>
        ) : (
          <EmptyState illustration="fridge" title={t("admin.boxes.history.empty")} />
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.boxes.history.columns.date")}
                </SortTh>
                <SortTh sortKey="kind" {...table.sorting}>
                  {t("admin.boxes.history.columns.kind")}
                </SortTh>
                <SortTh sortKey="boxType" {...table.sorting}>
                  {t("admin.boxes.history.columns.boxType")}
                </SortTh>
                <SortTh numeric sortKey="count" {...table.sorting}>
                  {t("admin.boxes.history.columns.count")}
                </SortTh>
                <Th className="max-[720px]:hidden">{t("admin.boxes.history.columns.from")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.boxes.history.columns.to")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((movement) => (
                <HistoryRow key={movement.id} movement={movement} />
              ))}
            </tbody>
          </Table>
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      )}
    </section>
  );
}

function HistoryRow({ movement }: { movement: BoxMovement }) {
  const { t } = useTranslation();
  return (
    <tr>
      <Td className="num whitespace-nowrap">{formatDate(movement.created_at)}</Td>
      <Td>
        <Pill tone={KIND_TONES[movement.kind]}>{t(`admin.boxes.kindLabels.${movement.kind}`)}</Pill>
        {(movement.kind === "write_off" || movement.kind === "purchase") && movement.reason && (
          <span className="block text-[0.8rem] text-ink-2">
            {t("admin.boxes.history.reason")}: {movement.reason}
          </span>
        )}
      </Td>
      <Td>{t(`admin.boxes.types.${movement.box_type}`)}</Td>
      <Td numeric className="num">
        {formatBoxCount(movement.count)}
      </Td>
      <Td className="max-[720px]:hidden">{movement.from_holder_name ?? t("admin.boxes.outside")}</Td>
      <Td className="max-[720px]:hidden">{movement.to_holder_name ?? t("admin.boxes.outside")}</Td>
    </tr>
  );
}
