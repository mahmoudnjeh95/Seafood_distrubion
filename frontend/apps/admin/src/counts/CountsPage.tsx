import { startCount, useListCounts, useListLocations } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
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
import { canRecordStockChecks, COUNT_TONES, refreshAfterStockCheck } from "../losses/shared";
import { todayInTunis } from "../receipts/shared";

/** Choose a place and a day: the server makes the count sheet from what the place holds. */
function StartDialog({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const formId = useId();
  const locations = useListLocations({ status: "active" });
  const [location, setLocation] = useState("");
  const [day, setDay] = useState(todayInTunis);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const start = useMutation({
    mutationFn: () => startCount({ location: Number(location), counted_on: day }),
    onSuccess: async (count) => {
      toast.success(t("admin.counts.start.created", { number: count.number }));
      await refreshAfterStockCheck(queryClient);
      onDone();
      void navigate(`/stock/inventaires/${count.id}`);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.counts.sheet.actionError") });
    },
  });
  return (
    <DialogContent>
      <DialogTitle>{t("admin.counts.start.title")}</DialogTitle>
      <DialogDescription>{t("admin.counts.start.body")}</DialogDescription>
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          const found: Record<string, string> = {};
          if (!location) found.location = t("admin.counts.start.required");
          if (!day) found.counted_on = t("admin.counts.start.required");
          setErrors(found);
          if (Object.keys(found).length === 0) start.mutate();
        }}
      >
        <Field label={t("admin.counts.start.location")} htmlFor={`${formId}-location`} error={errors.location}>
          <Select value={location} onValueChange={setLocation}>
            <SelectTrigger id={`${formId}-location`} aria-invalid={errors.location ? true : undefined}>
              <SelectValue placeholder={t("admin.counts.start.choose")} />
            </SelectTrigger>
            <SelectContent>
              {(locations.data ?? []).map((place) => (
                <SelectItem key={place.id} value={String(place.id)}>
                  {place.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("admin.counts.start.date")} htmlFor={`${formId}-date`} error={errors.counted_on}>
          <Input
            id={`${formId}-date`}
            type="date"
            max={todayInTunis()}
            value={day}
            onChange={(event) => setDay(event.target.value)}
          />
        </Field>
        {errors.detail && <p className="text-[0.85rem] font-semibold text-bad">{errors.detail}</p>}
        <DialogFooter>
          <Button onClick={onDone}>{t("admin.counts.start.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={start.isPending}>
            {t("admin.counts.start.save")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

export function CountsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canRecord = canRecordStockChecks(session);
  const table = useServerTable();
  const [starting, setStarting] = useState(false);
  const counts = useListCounts(table.params, { query: { placeholderData: keepPreviousData } });
  const page = counts.data;
  const list = page?.results ?? [];

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.goods")} title={t("admin.counts.title")}>
        {canRecord && (
          <Button variant="primary" onClick={() => setStarting(true)}>
            <Icon name="plus" />
            {t("admin.counts.add")}
          </Button>
        )}
      </PageHeader>
      <StockTabs />

      {!canRecord && <p className="text-ink-2">{t("admin.counts.readOnly")}</p>}

      {counts.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : counts.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        <EmptyState illustration="fridge" title={t("admin.counts.empty")}>
          {t("admin.counts.emptyBody")}
        </EmptyState>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.counts.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.counts.columns.date")}
                </SortTh>
                <SortTh sortKey="location" {...table.sorting}>
                  {t("admin.counts.columns.location")}
                </SortTh>
                <Th className="max-[720px]:hidden">{t("admin.counts.columns.lines")}</Th>
                <Th>{t("admin.counts.columns.differences")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((count) => {
                const differences = count.lines.filter(
                  (line) => line.difference !== null && !/^-?0+(\.0+)?$/.test(line.difference),
                ).length;
                return (
                  <tr
                    key={count.id}
                    onClick={() => void navigate(`/stock/inventaires/${count.id}`)}
                    className="cursor-pointer hover:bg-surface-2"
                  >
                    <Td className="whitespace-nowrap">
                      <Link
                        to={`/stock/inventaires/${count.id}`}
                        className="num font-semibold text-ink hover:underline"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {count.number}
                      </Link>
                      <Pill className="ms-2" tone={COUNT_TONES[count.status]}>
                        {t(`admin.counts.statuses.${count.status}`)}
                      </Pill>
                    </Td>
                    <Td className="num whitespace-nowrap">{formatDate(count.counted_on)}</Td>
                    <Td>{count.location.name}</Td>
                    <Td className="whitespace-nowrap text-ink-2 max-[720px]:hidden">
                      {t("admin.counts.linesCount", { count: count.lines.length })}
                    </Td>
                    <Td className="whitespace-nowrap">
                      {count.status === "counting" ? "" : t("admin.counts.differencesCount", { count: differences })}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      )}

      <Dialog open={starting} onOpenChange={setStarting}>
        {starting && <StartDialog onDone={() => setStarting(false)} />}
      </Dialog>
    </>
  );
}
