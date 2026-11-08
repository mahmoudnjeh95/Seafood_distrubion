import {
  addDefaultMaintenanceTypes,
  createMaintenanceType,
  type MaintenanceType,
  type MaintenanceTargetEnum,
  updateMaintenanceType,
  useListMaintenanceTypes,
} from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Card, Field, Input, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { digits, refreshFleet, SELECT_CLASSES } from "./shared";

type Values = { name: string; every_km: string; every_months: string; warn_km: string; warn_days: string };

function valuesOf(kind: MaintenanceType): Values {
  return {
    name: kind.name,
    every_km: kind.every_km == null ? "" : String(kind.every_km),
    every_months: kind.every_months == null ? "" : String(kind.every_months),
    warn_km: String(kind.warn_km ?? 1000),
    warn_days: String(kind.warn_days ?? 15),
  };
}

function numberOrNull(value: string): number | null {
  return value === "" ? null : Number(value);
}

/** One kind of maintenance, every value editable in place (owner answer 3: all of it is a setting). */
function TypeRow({ kind, canEdit }: { kind: MaintenanceType; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Values>(() => valuesOf(kind));
  const [error, setError] = useState("");
  const months = kind.target !== "truck";
  const set = (field: keyof Values, value: string) => setValues((old) => ({ ...old, [field]: value }));
  const save = useMutation({
    mutationFn: (changes: Parameters<typeof updateMaintenanceType>[1]) => updateMaintenanceType(kind.id, changes),
    onSuccess: async () => {
      setError("");
      toast.success(t("admin.fleet.settingsSaved"));
      await refreshFleet(queryClient);
    },
    onError: (failure) => setError(Object.values(fieldErrors(failure))[0] ?? t("admin.fleet.failed")),
  });
  const cell = (field: keyof Values, label: string, size: number) => (
    <Input
      aria-label={`${label} · ${kind.name}`}
      inputMode="numeric"
      className="num max-w-28"
      disabled={!canEdit || (field === "every_km" && months) || (field === "warn_km" && months)}
      value={values[field]}
      onChange={(event) => set(field, digits(event.target.value, size))}
    />
  );
  return (
    <tr className={kind.is_active === false ? "opacity-60" : undefined}>
      <Td>
        <Input
          aria-label={`${t("admin.maintenance.name")} · ${kind.name}`}
          disabled={!canEdit}
          value={values.name}
          onChange={(event) => set("name", event.target.value)}
        />
      </Td>
      <Td>{t(`admin.maintenance.targets.${kind.target ?? "truck"}`)}</Td>
      <Td>{cell("every_km", t("admin.maintenance.everyKm"), 7)}</Td>
      <Td>{cell("every_months", t("admin.maintenance.everyMonths"), 3)}</Td>
      <Td>{cell("warn_km", t("admin.maintenance.warnKm"), 6)}</Td>
      <Td>{cell("warn_days", t("admin.maintenance.warnDays"), 3)}</Td>
      <Td className="whitespace-nowrap">
        {canEdit && (
          <>
            <Button
              variant="primary"
              disabled={save.isPending}
              onClick={() =>
                save.mutate({
                  name: values.name,
                  every_km: months ? null : numberOrNull(values.every_km),
                  every_months: numberOrNull(values.every_months),
                  warn_km: Number(values.warn_km || "0"),
                  warn_days: Number(values.warn_days || "0"),
                })
              }
            >
              {t("admin.fleet.save")}
            </Button>
            <Button
              variant="ghost"
              disabled={save.isPending}
              onClick={() => save.mutate({ is_active: !kind.is_active })}
            >
              {t(kind.is_active === false ? "admin.maintenance.restore" : "admin.maintenance.archive")}
            </Button>
          </>
        )}
        {error && <p className="mt-1 text-[0.78rem] font-semibold text-bad">{error}</p>}
      </Td>
    </tr>
  );
}

function NewType() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const ids = { name: useId(), target: useId(), km: useId(), months: useId() };
  const [name, setName] = useState("");
  const [target, setTarget] = useState<MaintenanceTargetEnum>("truck");
  const [km, setKm] = useState("");
  const [months, setMonths] = useState("");
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: () =>
      createMaintenanceType({
        name: name.trim(),
        target,
        every_km: target === "truck" ? numberOrNull(km) : null,
        every_months: numberOrNull(months),
      }),
    onSuccess: async () => {
      setName("");
      setKm("");
      setMonths("");
      setError("");
      await refreshFleet(queryClient);
    },
    onError: (failure) => setError(Object.values(fieldErrors(failure))[0] ?? t("admin.fleet.failed")),
  });
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Field label={t("admin.maintenance.name")} htmlFor={ids.name}>
        <Input id={ids.name} value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label={t("admin.maintenance.target")} htmlFor={ids.target}>
        <select
          id={ids.target}
          className={SELECT_CLASSES}
          value={target}
          onChange={(e) => setTarget(e.target.value as MaintenanceTargetEnum)}
        >
          {(["truck", "frigo", "cold_room"] as const).map((value) => (
            <option key={value} value={value}>
              {t(`admin.maintenance.targets.${value}`)}
            </option>
          ))}
        </select>
      </Field>
      {target === "truck" && (
        <div className="w-32">
          <Field label={t("admin.maintenance.everyKm")} htmlFor={ids.km}>
            <Input id={ids.km} inputMode="numeric" value={km} onChange={(e) => setKm(digits(e.target.value))} />
          </Field>
        </div>
      )}
      <div className="w-32">
        <Field label={t("admin.maintenance.everyMonths")} htmlFor={ids.months}>
          <Input
            id={ids.months}
            inputMode="numeric"
            value={months}
            onChange={(e) => setMonths(digits(e.target.value, 3))}
          />
        </Field>
      </div>
      <Button type="submit" variant="primary" disabled={name.trim() === "" || save.isPending}>
        {t("admin.maintenance.addType")}
      </Button>
      {error && <p className="w-full font-semibold text-bad">{error}</p>}
    </form>
  );
}

/** Paramètres entretien: the kinds of maintenance with their intervals and warnings (P10-T02, owner answer 3). */
export function TypesCard({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const types = useListMaintenanceTypes();
  const list = types.data ?? [];
  const defaults = useMutation({
    mutationFn: () => addDefaultMaintenanceTypes(),
    onSuccess: async (answer) => {
      toast.success(t("admin.maintenance.defaultsAdded", { count: answer.added }));
      await refreshFleet(queryClient);
    },
  });
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">{t("admin.maintenance.typesTitle")}</p>
        {canEdit && (
          <Button variant="ghost" disabled={defaults.isPending} onClick={() => defaults.mutate()}>
            {t("admin.maintenance.addDefaults")}
          </Button>
        )}
      </div>
      <p className="text-ink-2">{t("admin.maintenance.typesHint")}</p>
      {list.length > 0 && (
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.maintenance.name")}</Th>
              <Th>{t("admin.maintenance.target")}</Th>
              <Th>{t("admin.maintenance.everyKm")}</Th>
              <Th>{t("admin.maintenance.everyMonths")}</Th>
              <Th>{t("admin.maintenance.warnKm")}</Th>
              <Th>{t("admin.maintenance.warnDays")}</Th>
              <Th>{null}</Th>
            </tr>
          </thead>
          <tbody>
            {list.map((kind) => (
              <TypeRow
                key={`${kind.id}-${kind.name}-${kind.every_km}-${kind.every_months}`}
                kind={kind}
                canEdit={canEdit}
              />
            ))}
          </tbody>
        </Table>
      )}
      {canEdit && <NewType />}
    </Card>
  );
}
