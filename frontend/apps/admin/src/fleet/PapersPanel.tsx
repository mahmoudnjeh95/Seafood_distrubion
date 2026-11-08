import {
  allowTruckDay,
  type PaperStatus,
  type PaymentMethodEnum,
  recordPaper,
  useListPaperBoard,
  useListTruckDayAllowances,
} from "@frutti/api";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, Field, Input, MoneyInput, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { fieldErrors } from "../lib/errors";
import { PAPER_TONES, refreshFleet, SELECT_CLASSES, todayIso } from "./shared";

/** Type a paper issued or renewed: number, issuer, dates, cost, scan (P10-T04). */
function PaperForm({ row, onDone }: { row: PaperStatus; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const ids = {
    number: useId(),
    issuer: useId(),
    issued: useId(),
    expires: useId(),
    cost: useId(),
    method: useId(),
    note: useId(),
    scan: useId(),
  };
  const [number, setNumber] = useState(row.paper?.number ?? "");
  const [issuer, setIssuer] = useState(row.paper?.issuer ?? "");
  const [issued, setIssued] = useState(todayIso);
  const [expires, setExpires] = useState("");
  const [cost, setCost] = useState("");
  const [method, setMethod] = useState<PaymentMethodEnum>("cash");
  const [note, setNote] = useState("");
  const [scan, setScan] = useState<File | undefined>(undefined);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const amount = cost.trim() === "" ? "0" : parseDecimalInput(cost.trim(), 3);
  const save = useMutation({
    mutationFn: () =>
      recordPaper({
        kind: row.kind,
        ...(row.truck_id === null ? { employee: row.employee_id } : { truck: row.truck_id }),
        number: number.trim(),
        issuer: issuer.trim(),
        issued_on: issued || null,
        expires_on: expires,
        cost: amount ?? "0",
        payment_method: method,
        note: note.trim(),
        ...(scan === undefined ? {} : { scan }),
      }),
    onSuccess: async () => {
      toast.success(t("admin.papers.saved"));
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
      <Field label={t("admin.papers.number")} htmlFor={ids.number}>
        <Input id={ids.number} value={number} maxLength={60} onChange={(e) => setNumber(e.target.value)} />
      </Field>
      <Field label={t("admin.papers.issuer")} htmlFor={ids.issuer}>
        <Input id={ids.issuer} value={issuer} maxLength={150} onChange={(e) => setIssuer(e.target.value)} />
      </Field>
      <Field label={t("admin.papers.issuedOn")} htmlFor={ids.issued}>
        <Input id={ids.issued} type="date" value={issued} onChange={(e) => setIssued(e.target.value)} />
      </Field>
      <Field label={t("admin.papers.expiresOn")} htmlFor={ids.expires} error={errors.expires_on}>
        <Input id={ids.expires} type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
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
      <Field label={t("admin.papers.scan")} htmlFor={ids.scan} error={errors.scan}>
        <Input
          id={ids.scan}
          type="file"
          accept="image/*,application/pdf"
          onChange={(e) => setScan(e.target.files?.[0] ?? undefined)}
        />
      </Field>
      <Button type="submit" variant="primary" disabled={expires === "" || amount === null || save.isPending}>
        {t("admin.papers.save")}
      </Button>
      {Object.keys(errors).length > 0 && !errors.expires_on && !errors.cost && !errors.scan && (
        <p className="w-full font-semibold text-bad">{Object.values(errors)[0]}</p>
      )}
    </form>
  );
}

function PaperRow({ row, canEdit }: { row: PaperStatus; canEdit: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const paper = row.paper;
  return (
    <>
      <tr>
        <Td className="font-semibold">{row.subject}</Td>
        <Td>{t(`admin.papers.kinds.${row.kind}`)}</Td>
        <Td>{paper?.number || "—"}</Td>
        <Td>{paper ? formatDate(paper.expires_on) : "—"}</Td>
        <Td>
          <Pill tone={PAPER_TONES[row.state]}>
            {row.state === "expired"
              ? t("admin.papers.expiredSince", { count: -(row.days_left ?? 0) })
              : row.state === "missing"
                ? t("admin.papers.states.missing")
                : row.days_left === 0
                  ? t("admin.papers.today")
                  : t("admin.papers.daysLeft", { count: row.days_left ?? 0 })}
          </Pill>
        </Td>
        <Td>
          {paper?.scan_url ? (
            <a href={paper.scan_url} target="_blank" rel="noreferrer" className="font-semibold">
              {t("admin.fleet.seePhoto")}
            </a>
          ) : (
            "—"
          )}
          {paper && Number(paper.cost) > 0 && <span className="ml-2 text-ink-2">{formatMoney(paper.cost)}</span>}
        </Td>
        <Td>
          {canEdit && (
            <Button variant={row.state === "ok" ? "ghost" : "primary"} onClick={() => setOpen(!open)}>
              {t(paper ? "admin.papers.renew" : "admin.papers.add")}
            </Button>
          )}
        </Td>
      </tr>
      {open && (
        <tr>
          <Td colSpan={7}>
            <PaperForm row={row} onDone={() => setOpen(false)} />
          </Td>
        </tr>
      )}
    </>
  );
}

/** The papers of the trucks or of the people, the current one of each kind (P10-T04, owner answer 5). */
export function PapersPanel({ canEdit, filter }: { canEdit: boolean; filter?: (row: PaperStatus) => boolean }) {
  const { t } = useTranslation();
  const board = useListPaperBoard();
  const rows = (board.data ?? []).filter(filter ?? (() => true));
  const trucks = rows.filter((row) => row.truck_id !== null);
  const people = rows.filter((row) => row.employee_id !== null);
  const table = (list: PaperStatus[], title: string) =>
    list.length === 0 ? null : (
      <section aria-label={title} className="flex flex-col gap-3">
        <h2>{title}</h2>
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.papers.subject")}</Th>
                <Th>{t("admin.papers.kind")}</Th>
                <Th>{t("admin.papers.number")}</Th>
                <Th>{t("admin.papers.expiresOn")}</Th>
                <Th>{t("admin.fleet.warnings")}</Th>
                <Th>{t("admin.papers.scan")}</Th>
                <Th>{null}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((row) => (
                <PaperRow
                  key={`${row.kind}-${row.truck_id ?? ""}-${row.employee_id ?? ""}-${row.paper?.id ?? ""}`}
                  row={row}
                  canEdit={canEdit}
                />
              ))}
            </tbody>
          </Table>
        </Card>
      </section>
    );
  if (board.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  return (
    <>
      {table(trucks, t("admin.papers.truckTitle"))}
      {table(people, t("admin.papers.peopleTitle"))}
    </>
  );
}

/** The owner lets a truck out one day although its assurance or visite technique has expired (owner answer 5b). */
export function DayAllowance({ truckId, isOwner }: { truckId: number; isOwner: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const ids = { date: useId(), reason: useId() };
  const allowances = useListTruckDayAllowances(truckId);
  const [date, setDate] = useState(todayIso);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: () => allowTruckDay(truckId, { date, reason: reason.trim() }),
    onSuccess: async () => {
      setReason("");
      setError("");
      toast.success(t("admin.papers.allowed"));
      await queryClient.invalidateQueries({
        predicate: (query) => typeof query.queryKey[0] === "string" && query.queryKey[0].includes("/day-allowances"),
      });
    },
    onError: (failure) => setError(Object.values(fieldErrors(failure))[0] ?? t("admin.fleet.failed")),
  });
  const list = allowances.data ?? [];
  if (!isOwner && list.length === 0) return null;
  return (
    <Card className="space-y-2">
      <p className="font-semibold">{t("admin.papers.allowTitle")}</p>
      <p className="text-ink-2">{t("admin.papers.allowHint")}</p>
      {isOwner && (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <Field label={t("admin.papers.date")} htmlFor={ids.date}>
            <Input id={ids.date} type="date" value={date} min={todayIso()} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <div className="min-w-64 flex-1">
            <Field label={t("admin.fleet.reason")} htmlFor={ids.reason}>
              <Input id={ids.reason} value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </div>
          <Button type="submit" variant="primary" disabled={reason.trim() === "" || save.isPending}>
            {t("admin.papers.allow")}
          </Button>
          {error && <p className="w-full font-semibold text-bad">{error}</p>}
        </form>
      )}
      {list.length > 0 && (
        <ul className="text-[0.9rem]">
          {list.map((row) => (
            <li key={row.id}>
              {formatDate(row.date)} · {row.reason} <span className="text-ink-2">· {row.allowed_by}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
