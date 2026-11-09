import {
  type ColdChainPlace,
  recordTemperature,
  setTemperatureRange,
  useGetColdChain,
  useListTemperatureReadings,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDateTime, formatTemperature, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  cn,
  EmptyState,
  Input,
  PageHeader,
  Pager,
  Pill,
  Table,
  Td,
  Th,
  toast,
  useServerTable,
} from "@frutti/ui";
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { StockTabs } from "../lib/StockTabs";
import { canRecordReceipts } from "../receipts/shared";

const REFRESHED = ["/api/v1/cold-chain", "/api/v1/temperatures"];

function rangeText(place: ColdChainPlace, none: string): string {
  if (place.temp_min === null && place.temp_max === null) return none;
  if (place.temp_min === null) return `≤ ${formatTemperature(place.temp_max ?? "")}`;
  if (place.temp_max === null) return `≥ ${formatTemperature(place.temp_min)}`;
  return `${formatTemperature(place.temp_min)} → ${formatTemperature(place.temp_max)}`;
}

/** One place: its range (editable), its last reading, and a field to type a new one. */
function PlaceCard({ place, canWrite }: { place: ColdChainPlace; canWrite: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [celsius, setCelsius] = useState("");
  const [note, setNote] = useState("");
  const [editRange, setEditRange] = useState(false);
  const [low, setLow] = useState(place.temp_min ?? "");
  const [high, setHigh] = useState(place.temp_max ?? "");
  const [error, setError] = useState("");
  const refresh = () =>
    queryClient.invalidateQueries({
      predicate: (query) => REFRESHED.some((prefix) => String(query.queryKey[0]).startsWith(prefix)),
    });
  const record = useMutation({
    mutationFn: () => recordTemperature({ location: place.id, celsius: celsius.trim(), note: note.trim() }),
    onSuccess: async (reading) => {
      if (reading.out_of_range) toast.error(t("admin.coldChain.outOfRange", { place: place.name }));
      else toast.success(t("admin.coldChain.saved"));
      setCelsius("");
      setNote("");
      setError("");
      await refresh();
    },
    onError: (failure) => setError(Object.values(fieldErrors(failure))[0] ?? t("admin.coldChain.failed")),
  });
  const range = useMutation({
    mutationFn: () => setTemperatureRange(place.id, { temp_min: low.trim() || null, temp_max: high.trim() || null }),
    onSuccess: async () => {
      setEditRange(false);
      setError("");
      await refresh();
    },
    onError: (failure) => setError(Object.values(fieldErrors(failure))[0] ?? t("admin.coldChain.failed")),
  });
  const last = place.last;

  return (
    <Card className={cn("flex flex-col gap-2", last?.out_of_range && "border-bad")}>
      <div className="flex items-center justify-between gap-2">
        <CardTitle className="mb-0">{place.name}</CardTitle>
        {place.alerts_7_days > 0 && (
          <Pill tone="bad">{t("admin.coldChain.alerts", { count: place.alerts_7_days })}</Pill>
        )}
      </div>
      <p className="text-[0.88rem] text-ink-2">
        {t("admin.coldChain.range")} : {rangeText(place, t("admin.coldChain.noRange"))}
        {canWrite && !editRange && (
          <button
            type="button"
            className="ms-2 font-semibold text-sea hover:underline"
            onClick={() => setEditRange(true)}
          >
            {t("admin.coldChain.editRange")}
          </button>
        )}
      </p>
      {editRange && (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label={t("admin.coldChain.min")}
            placeholder={t("admin.coldChain.min")}
            inputMode="decimal"
            value={low}
            onChange={(event) => setLow(event.target.value)}
            className="w-24"
          />
          <Input
            aria-label={t("admin.coldChain.max")}
            placeholder={t("admin.coldChain.max")}
            inputMode="decimal"
            value={high}
            onChange={(event) => setHigh(event.target.value)}
            className="w-24"
          />
          <Button disabled={range.isPending} onClick={() => range.mutate()}>
            {t("admin.coldChain.saveRange")}
          </Button>
        </div>
      )}
      <p>
        {last ? (
          <>
            <span className={cn("num text-[1.4rem] font-bold", last.out_of_range && "text-bad")}>
              {formatTemperature(last.celsius)}
            </span>
            <span className="ms-2 text-[0.85rem] text-ink-2">
              {formatDateTime(last.taken_at)}
              {last.taken_by && ` · ${last.taken_by}`}
            </span>
          </>
        ) : (
          <span className="text-ink-2">{t("admin.coldChain.never")}</span>
        )}
      </p>
      <p className="text-[0.8rem] text-ink-2">{t("admin.coldChain.today", { count: place.readings_today })}</p>
      {canWrite && (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            record.mutate();
          }}
        >
          <Input
            aria-label={t("admin.coldChain.celsius")}
            placeholder="°C"
            inputMode="decimal"
            value={celsius}
            onChange={(event) => setCelsius(event.target.value)}
            className="w-24"
          />
          <Input
            aria-label={t("admin.coldChain.note")}
            placeholder={t("admin.coldChain.note")}
            value={note}
            maxLength={255}
            onChange={(event) => setNote(event.target.value)}
            className="min-w-32 flex-1"
          />
          <Button type="submit" variant="primary" disabled={record.isPending || celsius.trim() === ""}>
            {t("admin.coldChain.record")}
          </Button>
        </form>
      )}
      {error && <p className="text-[0.8rem] font-semibold text-bad">{error}</p>}
    </Card>
  );
}

/** Stock › Températures (D-303): the HACCP log of the cold rooms and trucks. */
export function ColdChainPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canWrite = canRecordReceipts(session);
  const places = useGetColdChain();
  const [alertsOnly, setAlertsOnly] = useState(false);
  const table = useServerTable();
  const readings = useListTemperatureReadings(
    { ...table.params, out_of_range: alertsOnly },
    { query: { placeholderData: keepPreviousData } },
  );

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.stock")} title={t("admin.coldChain.title")} />
      <StockTabs />
      <p className="text-[0.9rem] text-ink-2">{t("admin.coldChain.intro")}</p>
      {places.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : (places.data ?? []).length === 0 ? (
        <EmptyState illustration="fish" title={t("admin.coldChain.noPlace")} />
      ) : (
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(18rem,1fr))]">
          {(places.data ?? []).map((place) => (
            <PlaceCard key={`${place.id}-${place.temp_min}-${place.temp_max}`} place={place} canWrite={canWrite} />
          ))}
        </div>
      )}
      <Card className="p-2">
        <div className="flex items-center justify-between gap-2 px-2.5 pt-2">
          <CardTitle className="mb-0">{t("admin.coldChain.log")}</CardTitle>
          <label className="flex items-center gap-2 text-[0.9rem]">
            <input
              type="checkbox"
              checked={alertsOnly}
              onChange={(event) => {
                setAlertsOnly(event.target.checked);
                table.backToFirstPage();
              }}
              className="size-4 accent-coral"
            />
            {t("admin.coldChain.alertsOnly")}
          </label>
        </div>
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.coldChain.when")}</Th>
              <Th>{t("admin.coldChain.place")}</Th>
              <Th numeric>{t("admin.coldChain.celsius")}</Th>
              <Th>{t("admin.coldChain.by")}</Th>
              <Th className="max-[720px]:hidden">{t("admin.coldChain.note")}</Th>
            </tr>
          </thead>
          <tbody>
            {(readings.data?.results ?? []).map((row) => (
              <tr key={row.id}>
                <Td className="num whitespace-nowrap">{formatDateTime(row.taken_at)}</Td>
                <Td>{row.location.name}</Td>
                <Td numeric className={cn("font-semibold", row.out_of_range && "text-bad")}>
                  {formatTemperature(row.celsius)}
                </Td>
                <Td>{row.taken_by || "—"}</Td>
                <Td className="max-[720px]:hidden">{row.note}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {readings.data && <Pager {...table.pager(readings.data.count)} />}
      </Card>
    </>
  );
}
