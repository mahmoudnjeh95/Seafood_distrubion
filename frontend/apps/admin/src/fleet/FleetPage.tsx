import {
  correctTruckOdometer,
  type FleetOdometerRow,
  getGetMaintenanceSettingsQueryKey,
  getListFleetOdometerQueryKey,
  getListTruckOdometerQueryKey,
  updateMaintenanceSettings,
  useGetMaintenanceSettings,
  useListFleetOdometer,
  useListLocations,
  useListTruckOdometer,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDateTime, useTranslation } from "@frutti/i18n";
import { Button, Card, Field, Input, PageHeader, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router";

import { fieldErrors } from "../lib/errors";
import { DayAllowance, PapersPanel } from "./PapersPanel";
import { PlansPanel } from "./PlansPanel";
import { digits, formatKm } from "./shared";
import { TypesCard } from "./TypesCard";

/** The office sets a truck's compteur, with its reason (a typo, a new truck, a compteur replaced). */
function CorrectionForm({ truckId }: { truckId: number }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const kmId = useId();
  const noteId = useId();
  const [km, setKm] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => correctTruckOdometer(truckId, { km: Number(km), note: note.trim() }),
    onSuccess: async () => {
      setErrors({});
      setKm("");
      setNote("");
      toast.success(t("admin.fleet.corrected"));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: getListTruckOdometerQueryKey(truckId) }),
        queryClient.invalidateQueries({ queryKey: getListFleetOdometerQueryKey() }),
      ]);
    },
    onError: (failure) => setErrors(fieldErrors(failure)),
  });
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <div className="w-40">
        <Field label={t("admin.fleet.km")} htmlFor={kmId} error={errors.km}>
          <Input id={kmId} inputMode="numeric" value={km} onChange={(event) => setKm(digits(event.target.value))} />
        </Field>
      </div>
      <div className="min-w-64 flex-1">
        <Field label={t("admin.fleet.reason")} htmlFor={noteId} error={errors.note}>
          <Input id={noteId} value={note} maxLength={300} onChange={(event) => setNote(event.target.value)} />
        </Field>
      </div>
      <Button type="submit" variant="primary" disabled={km === "" || note.trim() === "" || save.isPending}>
        {t("admin.fleet.correct")}
      </Button>
    </form>
  );
}

/** The compteur readings of one truck, the latest first, with photos and warnings. */
function TruckReadings({ row, canEdit }: { row: FleetOdometerRow; canEdit: boolean }) {
  const { t } = useTranslation();
  const readings = useListTruckOdometer(row.truck_id);
  const list = readings.data ?? [];
  return (
    <section aria-label={t("admin.fleet.readingsOf", { name: row.name })} className="flex flex-col gap-3">
      <h2>{t("admin.fleet.readingsOf", { name: row.name })}</h2>
      {canEdit && (
        <Card className="space-y-2">
          <p className="font-semibold">{t("admin.fleet.correctTitle")}</p>
          <p className="text-ink-2">{t("admin.fleet.correctHint")}</p>
          <CorrectionForm truckId={row.truck_id} />
        </Card>
      )}
      {list.length === 0 ? (
        <p className="text-ink-2">{t(readings.isPending ? "common.loading" : "admin.fleet.noReadings")}</p>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.fleet.when")}</Th>
                <Th>{t("admin.fleet.km")}</Th>
                <Th>{t("admin.fleet.driven")}</Th>
                <Th>{t("admin.fleet.by")}</Th>
                <Th>{t("admin.fleet.note")}</Th>
                <Th>{t("admin.fleet.photo")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((reading) => (
                <tr key={reading.id}>
                  <Td>{formatDateTime(reading.created_at)}</Td>
                  <Td className="num font-semibold">{formatKm(reading.km)}</Td>
                  <Td>
                    <span className="num">{formatKm(reading.driven_km)}</span>
                    {reading.warning === "big_jump" && (
                      <Pill tone="bad" className="ml-2">
                        {t("admin.fleet.bigJump")}
                      </Pill>
                    )}
                  </Td>
                  <Td>
                    {reading.recorded_by}
                    {reading.source === "office" && (
                      <Pill tone="neutral" className="ml-2">
                        {t("admin.fleet.correction")}
                      </Pill>
                    )}
                  </Td>
                  <Td className="text-ink-2">{reading.note || "—"}</Td>
                  <Td>
                    {reading.photo_url ? (
                      <a href={reading.photo_url} target="_blank" rel="noreferrer" className="font-semibold">
                        {t("admin.fleet.seePhoto")}
                      </a>
                    ) : (
                      "—"
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </section>
  );
}

/** Paramètres entretien (D-295): for now the km a truck may drive in a day before a reading is flagged. */
function SettingsCard({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const id = useId();
  const settings = useGetMaintenanceSettings();
  const [value, setValue] = useState<string | null>(null);
  const [error, setError] = useState("");
  const shown = value ?? (settings.data ? String(settings.data.max_day_km) : "");
  const save = useMutation({
    mutationFn: () => updateMaintenanceSettings({ max_day_km: Number(shown) }),
    onSuccess: async () => {
      setError("");
      setValue(null);
      toast.success(t("admin.fleet.settingsSaved"));
      await queryClient.invalidateQueries({ queryKey: getGetMaintenanceSettingsQueryKey() });
    },
    onError: (failure) => setError(fieldErrors(failure).max_day_km ?? t("admin.fleet.failed")),
  });
  return (
    <Card className="space-y-2">
      <p className="font-semibold">{t("admin.fleet.compteurSettings")}</p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-56">
          <Field label={t("admin.fleet.maxDayKm")} htmlFor={id} error={error || undefined}>
            <Input
              id={id}
              inputMode="numeric"
              disabled={!canEdit}
              value={shown}
              onChange={(event) => setValue(digits(event.target.value).slice(0, 4))}
            />
          </Field>
        </div>
        {canEdit && (
          <Button
            variant="primary"
            disabled={shown === "" || value === null || save.isPending}
            onClick={() => save.mutate()}
          >
            {t("admin.fleet.save")}
          </Button>
        )}
      </div>
      <p className="text-ink-2">{t("admin.fleet.maxDayKmHint")}</p>
    </Card>
  );
}

/** The days before a paper expires when the office is warned (30, 15, 7 by default). */
function PaperWarningsCard({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const id = useId();
  const settings = useGetMaintenanceSettings();
  const [value, setValue] = useState<string | null>(null);
  const [error, setError] = useState("");
  const shown = value ?? (settings.data?.paper_warn_days ?? []).join(", ");
  const days = shown
    .split(/[^0-9]+/)
    .filter((part) => part !== "")
    .map(Number);
  const save = useMutation({
    mutationFn: () => updateMaintenanceSettings({ paper_warn_days: days }),
    onSuccess: async () => {
      setError("");
      setValue(null);
      toast.success(t("admin.fleet.settingsSaved"));
      await queryClient.invalidateQueries({ queryKey: getGetMaintenanceSettingsQueryKey() });
    },
    onError: (failure) => setError(Object.values(fieldErrors(failure))[0] ?? t("admin.fleet.failed")),
  });
  return (
    <Card className="space-y-2">
      <p className="font-semibold">{t("admin.papers.warnTitle")}</p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-56">
          <Field label={t("admin.papers.warnDays")} htmlFor={id} error={error || undefined}>
            <Input id={id} disabled={!canEdit} value={shown} onChange={(event) => setValue(event.target.value)} />
          </Field>
        </div>
        {canEdit && (
          <Button
            variant="primary"
            disabled={days.length === 0 || value === null || save.isPending}
            onClick={() => save.mutate()}
          >
            {t("admin.fleet.save")}
          </Button>
        )}
      </div>
      <p className="text-ink-2">{t("admin.papers.warnHint")}</p>
    </Card>
  );
}

/** The company's cold rooms and their monthly service (P10-T03, owner answer 4). */
function ColdRooms({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const rooms = useListLocations({ kind: "cold_room" });
  return (
    <>
      {(rooms.data ?? []).map((room) => (
        <PlansPanel
          key={`room-${room.id}`}
          subject={{ location: room.id }}
          title={t("admin.maintenance.plansOf", { name: room.name })}
          canEdit={canEdit}
        />
      ))}
    </>
  );
}

/** "Flotte & entretien" (Phase 10, D-295): each truck's compteur as the driver types it when sending the day. */
export function FleetPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canEdit = session.role === "owner" || session.role === "manager";
  const [params, setParams] = useSearchParams();
  const fleet = useListFleetOdometer();
  const rows = fleet.data ?? [];
  const chosen = rows.find((row) => String(row.truck_id) === params.get("camion"));
  return (
    <>
      <PageHeader eyebrow={t("admin.groups.goods")} title={t("admin.fleet.title")} />
      <p className="text-ink-2">{t("admin.fleet.intro")}</p>
      {rows.length === 0 ? (
        <p className="text-ink-2">{t(fleet.isPending ? "common.loading" : "admin.fleet.noTrucks")}</p>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.fleet.truck")}</Th>
                <Th>{t("admin.fleet.plate")}</Th>
                <Th>{t("admin.fleet.lastKm")}</Th>
                <Th>{t("admin.fleet.when")}</Th>
                <Th>{t("admin.fleet.by")}</Th>
                <Th>{t("admin.fleet.warnings")}</Th>
                <Th>{null}</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.truck_id} className={row === chosen ? "bg-sea-soft" : undefined}>
                  <Td className="font-semibold">{row.name}</Td>
                  <Td>{row.plate}</Td>
                  <Td className="num font-semibold">{formatKm(row.last?.km)}</Td>
                  <Td>{row.last ? formatDateTime(row.last.created_at) : "—"}</Td>
                  <Td>{row.last?.recorded_by ?? "—"}</Td>
                  <Td>
                    {row.warnings > 0 ? (
                      <Pill tone="bad">{t("admin.fleet.warningCount", { count: row.warnings })}</Pill>
                    ) : row.last === null ? (
                      <Pill tone="warn">{t("admin.fleet.noReading")}</Pill>
                    ) : (
                      <Pill tone="good">{t("admin.fleet.ok")}</Pill>
                    )}
                  </Td>
                  <Td>
                    <Button variant="ghost" onClick={() => setParams({ camion: String(row.truck_id) })}>
                      {t("admin.fleet.open")}
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
      {chosen && (
        <PlansPanel
          key={`plans-${chosen.truck_id}`}
          subject={{ truck: chosen.truck_id }}
          title={t("admin.maintenance.plansOf", { name: chosen.name })}
          canEdit={canEdit}
        />
      )}
      {chosen && <DayAllowance truckId={chosen.truck_id} isOwner={session.role === "owner"} />}
      {chosen && <TruckReadings key={chosen.truck_id} row={chosen} canEdit={canEdit} />}
      <ColdRooms canEdit={canEdit} />
      <PapersPanel canEdit={canEdit} />
      <h2>{t("admin.fleet.settings")}</h2>
      <SettingsCard canEdit={canEdit} />
      <PaperWarningsCard canEdit={canEdit} />
      <TypesCard canEdit={canEdit} />
    </>
  );
}
