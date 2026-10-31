import type { InstrumentStatusEnum } from "@frutti/api";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Input,
  Pill,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@frutti/ui";
import { useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { type ListFilters, type ListState, NO_CHOICE, statusTone } from "./listFilters";

/** Days, means and state of a règlements list (P9-T03b). */
export function PaymentListFilters<M extends string>({
  filters,
  onChange,
  methods,
  methodLabel,
}: {
  filters: ListFilters<M>;
  onChange: (filters: ListFilters<M>) => void;
  methods: readonly M[];
  methodLabel: (method: M) => string;
}) {
  const { t } = useTranslation();
  const id = useId();
  const states: ListState[] = ["active", "unallocated", "voided"];
  return (
    <>
      <Field label={t("admin.treasury.list.from")} htmlFor={`${id}-from`} className="w-40">
        <Input
          id={`${id}-from`}
          type="date"
          value={filters.dateFrom}
          onChange={(event) => onChange({ ...filters, dateFrom: event.target.value })}
        />
      </Field>
      <Field label={t("admin.treasury.list.to")} htmlFor={`${id}-to`} className="w-40">
        <Input
          id={`${id}-to`}
          type="date"
          value={filters.dateTo}
          onChange={(event) => onChange({ ...filters, dateTo: event.target.value })}
        />
      </Field>
      <Field label={t("admin.treasury.list.method")} htmlFor={`${id}-method`} className="w-44">
        <Select
          value={filters.method || NO_CHOICE}
          onValueChange={(value) => onChange({ ...filters, method: value === NO_CHOICE ? "" : (value as M) })}
        >
          <SelectTrigger id={`${id}-method`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_CHOICE}>{t("admin.treasury.list.allMethods")}</SelectItem>
            {methods.map((method) => (
              <SelectItem key={method} value={method}>
                {methodLabel(method)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label={t("admin.treasury.list.state")} htmlFor={`${id}-state`} className="w-44">
        <Select
          value={filters.state || NO_CHOICE}
          onValueChange={(value) => onChange({ ...filters, state: value === NO_CHOICE ? "" : (value as ListState) })}
        >
          <SelectTrigger id={`${id}-state`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_CHOICE}>{t("admin.treasury.list.allStates")}</SelectItem>
            {states.map((state) => (
              <SelectItem key={state} value={state}>
                {t(`admin.treasury.list.states.${state}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
    </>
  );
}

type Totals = {
  count: number;
  voided: number;
  total: string;
  allocated: string;
  unallocated: string;
  by_method: Record<string, string>;
};

/** What the filtered règlements add up to (voided ones left out), by means, with the Excel file of the list. */
export function PaymentTotalsCard({
  totals,
  methodLabel,
  restLabel,
  exportUrl,
}: {
  totals: Totals | undefined;
  methodLabel: (method: string) => string;
  /** "Reste en crédit" (customers) or "Avances" (suppliers). */
  restLabel: string;
  exportUrl: string;
}) {
  const { t } = useTranslation();
  return (
    <Card className="flex flex-wrap items-center gap-x-8 gap-y-3 p-3" aria-label={t("admin.treasury.list.totals")}>
      {totals ? (
        <>
          <dl className="flex flex-wrap gap-x-8 gap-y-2">
            <Figure label={t("admin.treasury.list.count")} value={String(totals.count)} />
            <Figure label={t("admin.treasury.list.total")} value={formatMoney(totals.total)} strong />
            <Figure label={t("admin.treasury.list.allocated")} value={formatMoney(totals.allocated)} />
            <Figure label={restLabel} value={formatMoney(totals.unallocated)} />
          </dl>
          <ul className="flex flex-wrap gap-2">
            {Object.entries(totals.by_method).map(([method, amount]) => (
              <li key={method}>
                <Pill tone="sea">
                  {methodLabel(method)} · <span className="num">{formatMoney(amount)}</span>
                </Pill>
              </li>
            ))}
          </ul>
          {totals.voided > 0 && (
            <span className="text-[0.82rem] text-ink-2">
              {t("admin.treasury.list.voidedLeftOut", { count: totals.voided })}
            </span>
          )}
        </>
      ) : (
        <span className="text-ink-2">{t("common.loading")}</span>
      )}
      <Button asChild className="ms-auto">
        <a href={exportUrl} download>
          {t("admin.treasury.list.export")}
        </a>
      </Button>
    </Card>
  );
}

function Figure({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={strong ? "num text-lg font-bold" : "num text-lg"}>{value}</dd>
    </div>
  );
}

type LineLike = {
  id: number;
  method: string;
  amount: string;
  reference: string;
  instrument: { number: string; bank_code: string; due_on: string; status: InstrumentStatusEnum } | null;
};

/** The means of a règlement as small chips: "Chèque 4401 · 1 000,000 DT". */
export function MeansChips({
  lines,
  methodLabel,
}: {
  lines: readonly LineLike[];
  methodLabel: (method: string) => string;
}) {
  return (
    <ul className="flex flex-wrap gap-1">
      {lines.map((line) => (
        <li key={line.id}>
          <Pill tone={line.instrument ? statusTone(line.instrument.status) : "neutral"}>
            {methodLabel(line.method)}
            {line.instrument ? ` ${line.instrument.number}` : line.reference ? ` ${line.reference}` : ""} ·{" "}
            <span className="num">{formatMoney(line.amount)}</span>
          </Pill>
        </li>
      ))}
    </ul>
  );
}

/** The life of one effet, oldest step first. */
export function EffetHistory({
  events,
}: {
  events: readonly { to_status: InstrumentStatusEnum; happened_on: string; note: string; actor: string }[];
}) {
  const { t } = useTranslation();
  return (
    <ol className="flex flex-col gap-1 text-[0.85rem]">
      {events.map((event, index) => (
        <li key={index} className="flex flex-wrap items-center gap-2">
          <span className="num text-ink-2">{formatDate(event.happened_on)}</span>
          <Pill tone={statusTone(event.to_status)}>{t(`admin.treasury.status.${event.to_status}`)}</Pill>
          {event.note && <span className="text-ink-2">{event.note}</span>}
          {event.actor && <span className="text-ink-2">· {event.actor}</span>}
        </li>
      ))}
    </ol>
  );
}

/** "Annuler le règlement": asks the reason, then voids. The server says why when it refuses. */
export function VoidReasonDialog({
  title,
  body,
  onVoid,
  onClose,
}: {
  title: string;
  body: string;
  onVoid: (reason: string) => Promise<unknown>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{body}</DialogDescription>
        <Field label={t("admin.payments.void.reason")} htmlFor={`${id}-reason`} error={error}>
          <Input
            id={`${id}-reason`}
            value={reason}
            maxLength={255}
            onChange={(event) => setReason(event.target.value)}
          />
        </Field>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("admin.payments.dialog.cancel")}
          </Button>
          <Button
            variant="danger"
            disabled={pending}
            onClick={() => {
              if (!reason.trim()) {
                setError(t("admin.treasury.lines.problems.required"));
                return;
              }
              setPending(true);
              onVoid(reason.trim())
                .then(onClose)
                .catch((failure: unknown) => {
                  const found = fieldErrors(failure);
                  setError(found.reason ?? found.detail ?? Object.values(found)[0] ?? t("admin.payments.void.error"));
                })
                .finally(() => setPending(false));
            }}
          >
            {t("admin.payments.void.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
