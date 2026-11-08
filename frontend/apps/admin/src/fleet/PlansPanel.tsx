import {
  createMaintenancePlan,
  type MaintenancePlan,
  type PaymentMethodEnum,
  recordMaintenance,
  updateMaintenancePlan,
  useListMaintenancePlans,
  useListMaintenanceRecords,
  useListMaintenanceTypes,
} from "@frutti/api";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, Field, Input, MoneyInput, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { digits, formatKm, refreshFleet, SELECT_CLASSES, STATE_TONES, todayIso } from "./shared";

type Subject = { truck: number } | { location: number };

/** What is due: "dans 1 200 km", "le 12/03/2027", or both. */
function Due({ plan }: { plan: MaintenancePlan }) {
  const { t } = useTranslation();
  const parts: string[] = [];
  if (plan.km_left !== null) parts.push(t("admin.maintenance.kmLeft", { km: formatKm(plan.km_left) }));
  if (plan.due_on !== null) parts.push(t("admin.maintenance.dueOn", { date: formatDate(plan.due_on) }));
  if (plan.estimated_on !== null && plan.km_left !== null && plan.km_left > 0)
    parts.push(t("admin.maintenance.estimated", { date: formatDate(plan.estimated_on) }));
  return <span>{parts.length === 0 ? "—" : parts.join(" · ")}</span>;
}

function Every({ plan }: { plan: MaintenancePlan }) {
  const { t } = useTranslation();
  const parts: string[] = [];
  if (plan.every_km !== null) parts.push(formatKm(plan.every_km));
  if (plan.every_months !== null) parts.push(t("admin.maintenance.months", { count: plan.every_months }));
  return <span>{parts.join(t("admin.maintenance.or"))}</span>;
}

/** "Entretien effectué": date, compteur (truck types), garage, cost and how it was paid. */
function DoneForm({ plan, onDone }: { plan: MaintenancePlan; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const ids = { date: useId(), km: useId(), garage: useId(), cost: useId(), method: useId(), note: useId() };
  const onTruck = plan.type.target === "truck";
  const [date, setDate] = useState(todayIso);
  const [km, setKm] = useState(plan.current_km === null ? "" : String(plan.current_km));
  const [garage, setGarage] = useState("");
  const [cost, setCost] = useState("");
  const [method, setMethod] = useState<PaymentMethodEnum>("cash");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const amount = cost.trim() === "" ? "0" : parseDecimalInput(cost.trim(), 3);
  const save = useMutation({
    mutationFn: () =>
      recordMaintenance(plan.id, {
        done_on: date,
        km: onTruck && km !== "" ? Number(km) : null,
        garage: garage.trim(),
        note: note.trim(),
        cost: amount ?? "0",
        payment_method: method,
      }),
    onSuccess: async () => {
      toast.success(t("admin.maintenance.doneSaved"));
      await refreshFleet(queryClient);
      onDone();
    },
    onError: (failure) => setErrors(fieldErrors(failure)),
  });
  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-control border border-line p-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Field label={t("admin.maintenance.doneOn")} htmlFor={ids.date} error={errors.done_on}>
        <Input id={ids.date} type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} />
      </Field>
      {onTruck && (
        <div className="w-36">
          <Field label={t("admin.fleet.km")} htmlFor={ids.km} error={errors.km}>
            <Input id={ids.km} inputMode="numeric" value={km} onChange={(e) => setKm(digits(e.target.value))} />
          </Field>
        </div>
      )}
      <Field label={t("admin.maintenance.garage")} htmlFor={ids.garage}>
        <Input id={ids.garage} value={garage} maxLength={150} onChange={(e) => setGarage(e.target.value)} />
      </Field>
      <div className="w-36">
        <Field label={t("admin.maintenance.cost")} htmlFor={ids.cost} error={errors.cost}>
          <MoneyInput id={ids.cost} inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
        </Field>
      </div>
      <Field label={t("admin.maintenance.method")} htmlFor={ids.method}>
        <select
          id={ids.method}
          className={SELECT_CLASSES}
          value={method}
          onChange={(e) => setMethod(e.target.value as PaymentMethodEnum)}
        >
          {(["cash", "cheque", "transfer", "bill", "other"] as const).map((value) => (
            <option key={value} value={value}>
              {t(`admin.maintenance.methods.${value}`)}
            </option>
          ))}
        </select>
      </Field>
      <div className="min-w-48 flex-1">
        <Field label={t("admin.fleet.note")} htmlFor={ids.note}>
          <Input id={ids.note} value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
      <Button type="submit" variant="primary" disabled={amount === null || date === "" || save.isPending}>
        {t("admin.maintenance.saveDone")}
      </Button>
      <p className="w-full text-[0.78rem] text-ink-2">{t("admin.maintenance.costHint")}</p>
    </form>
  );
}

/** The jobs done on a plan. */
function History({ plan }: { plan: MaintenancePlan }) {
  const { t } = useTranslation();
  const records = useListMaintenanceRecords(plan.id);
  const list = records.data ?? [];
  if (list.length === 0)
    return <p className="text-ink-2">{t(records.isPending ? "common.loading" : "admin.maintenance.noRecords")}</p>;
  return (
    <ul className="space-y-1 text-[0.9rem]">
      {list.map((record) => (
        <li key={record.id}>
          {formatDate(record.done_on)}
          {record.km !== null && ` · ${formatKm(record.km)}`}
          {record.garage && ` · ${record.garage}`}
          {` · ${formatMoney(record.cost)}`}
          {record.expense_number && ` (${record.expense_number})`}
          {record.note && ` · ${record.note}`}
          <span className="text-ink-2"> · {record.recorded_by}</span>
        </li>
      ))}
    </ul>
  );
}

/** One followed maintenance: its state, what is due, and its actions. */
function PlanRow({ plan, canEdit }: { plan: MaintenancePlan; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState<"done" | "history" | null>(null);
  const stop = useMutation({
    mutationFn: () => updateMaintenancePlan(plan.id, { is_active: false }),
    onSuccess: () => refreshFleet(queryClient),
  });
  return (
    <>
      <tr>
        <Td className="font-semibold">{plan.type.name}</Td>
        <Td>
          <Every plan={plan} />
        </Td>
        <Td>
          {plan.last_done_on === null ? "—" : formatDate(plan.last_done_on)}
          {plan.last_done_km !== null && <span className="text-ink-2"> · {formatKm(plan.last_done_km)}</span>}
        </Td>
        <Td>
          <Due plan={plan} />
        </Td>
        <Td>
          <Pill tone={STATE_TONES[plan.state]}>{t(`admin.maintenance.states.${plan.state}`)}</Pill>
        </Td>
        <Td className="whitespace-nowrap">
          {canEdit && (
            <Button variant="primary" onClick={() => setOpen(open === "done" ? null : "done")}>
              {t("admin.maintenance.done")}
            </Button>
          )}
          <Button variant="ghost" onClick={() => setOpen(open === "history" ? null : "history")}>
            {t("admin.maintenance.history")}
          </Button>
          {canEdit && (
            <Button variant="ghost" disabled={stop.isPending} onClick={() => stop.mutate()}>
              {t("admin.maintenance.stop")}
            </Button>
          )}
        </Td>
      </tr>
      {open !== null && (
        <tr>
          <Td colSpan={6}>
            {open === "done" ? <DoneForm plan={plan} onDone={() => setOpen(null)} /> : <History plan={plan} />}
          </Td>
        </tr>
      )}
    </>
  );
}

/** Follow a new kind of maintenance here, with when it was last done (for a job done before the app). */
function AddPlanForm({ subject, targets, followed }: { subject: Subject; targets: string[]; followed: number[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const ids = { type: useId(), date: useId(), km: useId() };
  const types = useListMaintenanceTypes();
  const offered = (types.data ?? []).filter(
    (kind) => kind.is_active && targets.includes(kind.target ?? "truck") && !followed.includes(kind.id),
  );
  const [typeId, setTypeId] = useState("");
  const [date, setDate] = useState("");
  const [km, setKm] = useState("");
  const [error, setError] = useState("");
  const chosen = offered.find((kind) => String(kind.id) === typeId);
  const save = useMutation({
    mutationFn: () =>
      createMaintenancePlan({
        type: Number(typeId),
        ...subject,
        last_done_on: date || null,
        last_done_km: chosen?.target === "truck" && km !== "" ? Number(km) : null,
      }),
    onSuccess: async () => {
      setTypeId("");
      setDate("");
      setKm("");
      setError("");
      await refreshFleet(queryClient);
    },
    onError: (failure) => setError(Object.values(fieldErrors(failure))[0] ?? t("admin.fleet.failed")),
  });
  if (offered.length === 0) return <p className="text-ink-2">{t("admin.maintenance.nothingToAdd")}</p>;
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Field label={t("admin.maintenance.type")} htmlFor={ids.type}>
        <select id={ids.type} className={SELECT_CLASSES} value={typeId} onChange={(e) => setTypeId(e.target.value)}>
          <option value="">{t("admin.maintenance.choose")}</option>
          {offered.map((kind) => (
            <option key={kind.id} value={kind.id}>
              {kind.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t("admin.maintenance.lastDoneOn")} htmlFor={ids.date}>
        <Input id={ids.date} type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} />
      </Field>
      {chosen?.target === "truck" && chosen.every_km !== null && (
        <div className="w-36">
          <Field label={t("admin.maintenance.lastDoneKm")} htmlFor={ids.km}>
            <Input id={ids.km} inputMode="numeric" value={km} onChange={(e) => setKm(digits(e.target.value))} />
          </Field>
        </div>
      )}
      <Button type="submit" variant="primary" disabled={typeId === "" || save.isPending}>
        {t("admin.maintenance.follow")}
      </Button>
      {error && <p className="w-full font-semibold text-bad">{error}</p>}
    </form>
  );
}

/** The maintenance followed on one truck (and its frigo unit) or one cold room (P10-T02, P10-T03). */
export function PlansPanel({ subject, title, canEdit }: { subject: Subject; title: string; canEdit: boolean }) {
  const { t } = useTranslation();
  const plans = useListMaintenancePlans(subject);
  const list = plans.data ?? [];
  const targets = "truck" in subject ? ["truck", "frigo"] : ["cold_room"];
  return (
    <section aria-label={title} className="flex flex-col gap-3">
      <h2>{title}</h2>
      {list.length === 0 ? (
        <p className="text-ink-2">{t(plans.isPending ? "common.loading" : "admin.maintenance.noPlans")}</p>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.maintenance.type")}</Th>
                <Th>{t("admin.maintenance.every")}</Th>
                <Th>{t("admin.maintenance.lastDone")}</Th>
                <Th>{t("admin.maintenance.due")}</Th>
                <Th>{t("admin.fleet.warnings")}</Th>
                <Th>{null}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((plan) => (
                <PlanRow key={plan.id} plan={plan} canEdit={canEdit} />
              ))}
            </tbody>
          </Table>
        </Card>
      )}
      {canEdit && (
        <Card className="space-y-2">
          <p className="font-semibold">{t("admin.maintenance.addPlan")}</p>
          <AddPlanForm subject={subject} targets={targets} followed={list.map((plan) => plan.type.id)} />
        </Card>
      )}
    </section>
  );
}
