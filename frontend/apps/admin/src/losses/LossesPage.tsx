import { type LossStatusEnum, updateStockSettings, useGetStockSettings, useListLosses } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  EmptyState,
  Field,
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
  useServerTable,
} from "@frutti/ui";
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { StockTabs } from "../lib/StockTabs";
import { useDebounced } from "../lib/useDebounced";
import { canRecordStockChecks, isOwner, LOSS_TONES, refreshAfterStockCheck } from "./shared";

const STATUSES: LossStatusEnum[] = ["pending", "approved", "rejected"];

/** The owner's threshold: above it, a loss waits for approval. */
function ThresholdDialog({ current, onDone }: { current: string; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const inputId = useId();
  const [value, setValue] = useState(current.replace(".", ","));
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: (threshold: string) => updateStockSettings({ loss_approval_threshold: threshold }),
    onSuccess: async () => {
      toast.success(t("admin.losses.settings.saved"));
      await refreshAfterStockCheck(queryClient);
      onDone();
    },
    onError: (failure) =>
      setError(fieldErrors(failure).loss_approval_threshold ?? t("admin.losses.detail.actionError")),
  });
  return (
    <DialogContent>
      <DialogTitle>{t("admin.losses.settings.title")}</DialogTitle>
      <DialogDescription>{t("admin.losses.settings.body")}</DialogDescription>
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          const parsed = parseDecimalInput(value.trim(), 3);
          if (parsed === null || parsed.startsWith("-")) {
            setError(t("admin.losses.settings.weight"));
            return;
          }
          save.mutate(parsed);
        }}
      >
        <Field label={t("admin.losses.settings.threshold")} htmlFor={inputId} error={error}>
          <Input
            id={inputId}
            inputMode="decimal"
            className="num"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            aria-invalid={error ? true : undefined}
          />
        </Field>
        <DialogFooter>
          <Button onClick={onDone}>{t("admin.losses.settings.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {t("admin.losses.settings.save")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

export function LossesPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canRecord = canRecordStockChecks(session);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<LossStatusEnum | "">("");
  const table = useServerTable();
  const [editThreshold, setEditThreshold] = useState(false);
  const query = useDebounced(search.trim());

  const settings = useGetStockSettings();
  const losses = useListLosses(
    {
      ...table.params,
      ...(statusFilter ? { status: statusFilter } : {}),
      ...(query ? { search: query } : {}),
    },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = losses.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || statusFilter !== "";

  const statusButton = (value: LossStatusEnum | "", label: string) => (
    <button
      key={value || "all"}
      type="button"
      aria-pressed={statusFilter === value}
      onClick={() => {
        setStatusFilter(value);
        table.backToFirstPage();
      }}
      className={cn(
        "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
        statusFilter === value && "bg-surface text-ink shadow-card",
      )}
    >
      {label}
    </button>
  );

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.goods")} title={t("admin.losses.title")}>
        {canRecord && (
          <Button variant="primary" onClick={() => void navigate("/stock/pertes/nouvelle")}>
            <Icon name="plus" />
            {t("admin.losses.add")}
          </Button>
        )}
      </PageHeader>
      <StockTabs />

      {!canRecord && <p className="text-ink-2">{t("admin.losses.readOnly")}</p>}
      {settings.data && (
        <p className="flex flex-wrap items-center gap-3 text-ink-2">
          <span>
            {t("admin.losses.threshold", { threshold: formatQuantity(settings.data.loss_approval_threshold) })}
          </span>
          {isOwner(session) && (
            <Button variant="ghost" onClick={() => setEditThreshold(true)}>
              {t("admin.losses.changeThreshold")}
            </Button>
          )}
        </p>
      )}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.losses.search")}
          placeholder={t("admin.losses.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div role="group" aria-label={t("admin.losses.statusFilter")} className="flex rounded-control bg-surface-2 p-1">
          {statusButton("", t("admin.losses.allStatuses"))}
          {STATUSES.map((value) => statusButton(value, t(`admin.losses.statuses.${value}`)))}
        </div>
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.losses.count", { count: page.count })}
        </span>
      </Card>

      {losses.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : losses.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.losses.noMatch")}</p>
        ) : (
          <EmptyState illustration="mussel" title={t("admin.losses.empty")}>
            {t("admin.losses.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.losses.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.losses.columns.date")}
                </SortTh>
                <SortTh sortKey="product" {...table.sorting}>
                  {t("admin.losses.columns.product")}
                </SortTh>
                <Th className="max-[720px]:hidden">{t("admin.losses.columns.location")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.losses.columns.reason")}</Th>
                <Th numeric>{t("admin.losses.columns.quantity")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((loss) => (
                <tr
                  key={loss.id}
                  onClick={() => void navigate(`/stock/pertes/${loss.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="whitespace-nowrap">
                    <Link
                      to={`/stock/pertes/${loss.id}`}
                      className="num font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {loss.number}
                    </Link>
                    <Pill className="ms-2" tone={LOSS_TONES[loss.status]}>
                      {t(`admin.losses.statuses.${loss.status}`)}
                    </Pill>
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(loss.lost_on)}</Td>
                  <Td>
                    <span className="font-semibold">{loss.product.name}</span>
                    <div className="num text-[0.8rem] text-ink-2">{loss.product.reference}</div>
                  </Td>
                  <Td className="max-[720px]:hidden">{loss.location.name}</Td>
                  <Td className="max-[720px]:hidden">{t(`admin.losses.reasons.${loss.reason}`)}</Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatQuantity(loss.quantity)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      )}

      <Dialog open={editThreshold} onOpenChange={setEditThreshold}>
        {editThreshold && settings.data && (
          <ThresholdDialog current={settings.data.loss_approval_threshold} onDone={() => setEditThreshold(false)} />
        )}
      </Dialog>
    </>
  );
}
