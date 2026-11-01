import {
  createDayLabourer,
  type DayLabourer,
  type DayLabourerWrite,
  updateDayLabourer,
  useListDayLabourers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
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
  MoneyInput,
  PageHeader,
  Pill,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { type Status, StatusFilter } from "../lib/StatusFilter";
import { ExpensesTabs } from "./ExpensesTabs";
import { canWriteExpenses, refreshExpenses } from "./shared";

type Errors = Record<string, string>;

/** Add or change a day labourer: name, phone, usual pay for a day; archive one who no longer comes. */
function LabourerDialog({ labourer, onDone }: { labourer?: DayLabourer; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [name, setName] = useState(labourer?.name ?? "");
  const [phone, setPhone] = useState(labourer?.phone ?? "");
  const [pay, setPay] = useState(labourer?.usual_daily_pay?.replace(".", ",") ?? "");
  const [notes, setNotes] = useState(labourer?.notes ?? "");
  const [active, setActive] = useState(labourer?.is_active ?? true);
  const [errors, setErrors] = useState<Errors>({});
  const save = useMutation({
    mutationFn: (payload: DayLabourerWrite) =>
      labourer ? updateDayLabourer(labourer.id, payload) : createDayLabourer(payload),
    onSuccess: async (saved) => {
      toast.success(t("admin.labourers.saved", { name: saved.name }));
      await refreshExpenses(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.expenses.actionError") });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const typed = pay.trim();
    const parsed = typed ? parseDecimalInput(typed, 3) : "";
    const found: Errors = {};
    if (!name.trim()) found.name = t("admin.expenses.form.required");
    if (parsed === null || (parsed && (parsed.startsWith("-") || /^0+(\.0+)?$/.test(parsed)))) {
      found.usual_daily_pay = t("admin.expenses.form.amountInvalid");
    }
    setErrors(found);
    if (Object.keys(found).length > 0 || parsed === null) return;
    save.mutate({
      name: name.trim(),
      phone: phone.trim(),
      usual_daily_pay: parsed || null,
      notes: notes.trim(),
      is_active: active,
    });
  }

  const id = (field: string) => `${formId}-${field}`;
  return (
    <DialogContent>
      <DialogTitle>{labourer ? t("admin.labourers.editTitle") : t("admin.labourers.addTitle")}</DialogTitle>
      <DialogDescription>{t("admin.labourers.dialogBody")}</DialogDescription>
      <form noValidate onSubmit={submit} className="flex flex-col gap-3">
        <Field label={t("admin.labourers.form.name")} htmlFor={id("name")} error={errors.name}>
          <Input id={id("name")} value={name} onChange={(event) => setName(event.target.value)} autoComplete="off" />
        </Field>
        <Field label={t("admin.labourers.form.phone")} htmlFor={id("phone")} error={errors.phone}>
          <Input
            id={id("phone")}
            type="tel"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            autoComplete="off"
          />
        </Field>
        <Field label={t("admin.labourers.form.pay")} htmlFor={id("pay")} error={errors.usual_daily_pay}>
          <MoneyInput
            id={id("pay")}
            inputMode="decimal"
            className="num"
            value={pay}
            onChange={(event) => setPay(event.target.value)}
            autoComplete="off"
          />
        </Field>
        <Field label={t("admin.labourers.form.notes")} htmlFor={id("notes")} error={errors.notes}>
          <Input id={id("notes")} value={notes} onChange={(event) => setNotes(event.target.value)} autoComplete="off" />
        </Field>
        {labourer && (
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={!active} onChange={(event) => setActive(!event.target.checked)} />
            {t("admin.labourers.form.archived")}
          </label>
        )}
        {errors.detail && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail}
          </p>
        )}
        <DialogFooter>
          <Button onClick={onDone}>{t("admin.labourers.form.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {t("admin.labourers.form.save")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

/** "Journaliers": the people paid by the day. Not employees: no payroll, no CNSS. */
export function DayLabourersPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canWrite = canWriteExpenses(session);
  const [status, setStatus] = useState<Status>("active");
  const [editing, setEditing] = useState<DayLabourer | "new" | null>(null);
  const labourers = useListDayLabourers({ status });
  const list = labourers.data ?? [];

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.finance")} title={t("admin.labourers.title")}>
        {canWrite && (
          <Button variant="primary" onClick={() => setEditing("new")}>
            <Icon name="plus" />
            {t("admin.labourers.add")}
          </Button>
        )}
      </PageHeader>
      <ExpensesTabs />
      <p className="text-ink-2">{t("admin.labourers.intro")}</p>

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <StatusFilter
          value={status}
          onChange={setStatus}
          label={t("admin.labourers.statusFilter")}
          labels={{
            active: t("admin.labourers.statuses.active"),
            archived: t("admin.labourers.statuses.archived"),
            all: t("admin.labourers.statuses.all"),
          }}
        />
      </Card>

      {labourers.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : labourers.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        <EmptyState illustration="mix" title={t("admin.labourers.empty")}>
          {t("admin.labourers.emptyBody")}
        </EmptyState>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.labourers.columns.name")}</Th>
                <Th>{t("admin.labourers.columns.phone")}</Th>
                <Th numeric>{t("admin.labourers.columns.pay")}</Th>
                {canWrite && <Th className="w-0" />}
              </tr>
            </thead>
            <tbody>
              {list.map((labourer) => (
                <tr key={labourer.id}>
                  <Td>
                    <span className="font-semibold">{labourer.name}</span>
                    {!labourer.is_active && (
                      <Pill className="ms-2" tone="neutral">
                        {t("admin.labourers.archivedPill")}
                      </Pill>
                    )}
                    {labourer.notes && <div className="text-[0.8rem] text-ink-2">{labourer.notes}</div>}
                  </Td>
                  <Td className="num whitespace-nowrap">{labourer.phone || t("admin.expenses.detail.none")}</Td>
                  <Td numeric className="whitespace-nowrap">
                    {labourer.usual_daily_pay ? formatMoney(labourer.usual_daily_pay) : t("admin.labourers.varies")}
                  </Td>
                  {canWrite && (
                    <Td>
                      <Button
                        variant="ghost"
                        aria-label={t("admin.labourers.editOf", { name: labourer.name })}
                        onClick={() => setEditing(labourer)}
                      >
                        {t("admin.labourers.edit")}
                      </Button>
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        {editing !== null && (
          <LabourerDialog labourer={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />
        )}
      </Dialog>
    </>
  );
}
