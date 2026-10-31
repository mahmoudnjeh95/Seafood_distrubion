import {
  cashInstruments,
  createDeposit,
  recordUnpaidEffet,
  rejectIssuedEffet,
  returnInstruments,
  debitInstruments,
  type Instrument,
  type InstrumentKindEnum,
  type ListInstrumentsParams,
  useGetInstrumentTotals,
  useListBanks,
  useListDeposits,
  useListInstruments,
  withdrawInstruments,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
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
  Input,
  MoneyInput,
  PageHeader,
  Pill,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { keepPreviousData, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useOutletContext, useSearchParams } from "react-router";

import { sum } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { openPdf } from "../lib/pdf";
import { PdfButton } from "../lib/PdfButton";
import { useDebounced } from "../lib/useDebounced";
import { NO_CHOICE, statusTone } from "../payments/listFilters";
import { canCollect, todayInput } from "../payments/shared";
import { type PortfolioTab, TABS, TAB_QUERY, waitingLate } from "./portfolio";

const PAGE_SIZE = 100;

type Step = "deposit" | "cash" | "withdraw" | "debit" | "unpaid" | "return" | "reject";

/** The actions each tab offers on the ticked effets. */
const STEPS: Record<PortfolioTab, Step[]> = {
  toRemit: ["deposit", "cash"],
  atBank: ["cash", "unpaid", "withdraw"],
  cashed: ["unpaid"],
  unpaid: ["return"],
  issued: ["debit", "reject"],
  debited: [],
  deposits: [],
};

/** "Portefeuille" (P9-T04a, D-216): every cheque and traite by where it stands — to hand to the bank, at the bank,
 * cashed, ours waiting to be debited — with the bordereaux de remise. Tick effets, then act on them. */
export function PortfolioPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canWrite = canCollect(session);
  const [params, setParams] = useSearchParams();
  const tab = TABS.find((one) => one === params.get("onglet")) ?? "toRemit";
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<InstrumentKindEnum | "">("");
  const [bank, setBank] = useState("");
  const [dueFrom, setDueFrom] = useState("");
  const [dueTo, setDueTo] = useState("");
  const [ticked, setTicked] = useState<Record<number, Instrument>>({});
  const [step, setStep] = useState<Step | null>(null);
  const query = useDebounced(search.trim());
  const banks = useListBanks();
  const id = useId();

  const filters: ListInstrumentsParams = {
    ...(tab === "deposits" ? {} : TAB_QUERY[tab]),
    ...(query ? { search: query } : {}),
    ...(kind ? { kind } : {}),
    ...(bank ? { bank: Number(bank) } : {}),
    ...(dueFrom ? { due_from: dueFrom } : {}),
    ...(dueTo ? { due_to: dueTo } : {}),
  };
  const effets = useListInstruments(
    { ...filters, limit: PAGE_SIZE },
    { query: { enabled: tab !== "deposits", placeholderData: keepPreviousData } },
  );
  const totals = useGetInstrumentTotals(filters, {
    query: { enabled: tab !== "deposits", placeholderData: keepPreviousData },
  });
  const deposits = useListDeposits({ limit: 50 }, { query: { enabled: tab === "deposits" } });
  const rows = effets.data?.results ?? [];
  const chosen = Object.values(ticked);
  const today = todayInput();

  const switchTab = (next: PortfolioTab) => {
    setTicked({});
    setParams(next === "toRemit" ? {} : { onglet: next }, { replace: true });
  };
  const toggle = (row: Instrument) =>
    setTicked((current) => {
      const next = { ...current };
      if (next[row.id]) delete next[row.id];
      else next[row.id] = row;
      return next;
    });
  const allTicked = rows.length > 0 && rows.every((row) => ticked[row.id]);

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.finance")} title={t("admin.treasury.portfolio.title")} />
      <p className="text-ink-2">{t("admin.treasury.portfolio.intro")}</p>

      <nav
        aria-label={t("admin.treasury.portfolio.title")}
        className="flex flex-wrap gap-1 rounded-control bg-surface-2 p-1"
      >
        {TABS.map((one) => (
          <button
            key={one}
            type="button"
            aria-current={one === tab ? "page" : undefined}
            onClick={() => switchTab(one)}
            className={cn(
              "rounded-[7px] px-3 py-1.5 text-[0.9rem] font-semibold",
              one === tab ? "bg-surface text-ink shadow-card" : "text-ink-2",
            )}
          >
            {t(`admin.treasury.portfolio.tabs.${one}`)}
          </button>
        ))}
      </nav>

      {tab === "deposits" ? (
        <Card className="p-2">
          {deposits.isPending ? (
            <p className="p-2 text-ink-2">{t("common.loading")}</p>
          ) : (deposits.data?.results ?? []).length === 0 ? (
            <p className="p-2 text-ink-2">{t("admin.treasury.portfolio.noDeposit")}</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.treasury.portfolio.columns.deposit")}</Th>
                  <Th>{t("admin.treasury.portfolio.columns.day")}</Th>
                  <Th>{t("admin.treasury.lines.bank")}</Th>
                  <Th numeric>{t("admin.treasury.portfolio.columns.count")}</Th>
                  <Th numeric>{t("admin.treasury.list.total")}</Th>
                  <Th>{null}</Th>
                </tr>
              </thead>
              <tbody>
                {(deposits.data?.results ?? []).map((deposit) => (
                  <tr key={deposit.id}>
                    <Td className="num font-semibold">{deposit.number}</Td>
                    <Td className="num">{formatDate(deposit.deposited_on)}</Td>
                    <Td>{deposit.bank.code}</Td>
                    <Td numeric>{deposit.effets_count}</Td>
                    <Td numeric>{formatMoney(deposit.effets_total ?? "0")}</Td>
                    <Td className="text-end">
                      <PdfButton kind="bank_deposit" id={deposit.id} variant="ghost" />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      ) : (
        <>
          <Card className="filter-bar flex flex-wrap items-end gap-3 p-3">
            <Input
              type="search"
              aria-label={t("admin.treasury.portfolio.search")}
              placeholder={t("admin.treasury.portfolio.search")}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="min-w-52 flex-[2_1_14rem]"
            />
            <Field label={t("admin.treasury.split.kind")} htmlFor={`${id}-kind`} className="w-36">
              <Select
                value={kind || NO_CHOICE}
                onValueChange={(value) => setKind(value === NO_CHOICE ? "" : (value as InstrumentKindEnum))}
              >
                <SelectTrigger id={`${id}-kind`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_CHOICE}>{t("admin.treasury.portfolio.allKinds")}</SelectItem>
                  <SelectItem value="cheque">{t("admin.sales.methods.cheque")}</SelectItem>
                  <SelectItem value="bill">{t("admin.sales.methods.bill")}</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label={t("admin.treasury.lines.bank")} htmlFor={`${id}-bank`} className="w-44">
              <Select value={bank || NO_CHOICE} onValueChange={(value) => setBank(value === NO_CHOICE ? "" : value)}>
                <SelectTrigger id={`${id}-bank`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_CHOICE}>{t("admin.treasury.portfolio.allBanks")}</SelectItem>
                  {(banks.data ?? []).map((one) => (
                    <SelectItem key={one.id} value={String(one.id)}>
                      {one.code}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label={t("admin.treasury.portfolio.dueFrom")} htmlFor={`${id}-from`} className="w-40">
              <Input
                id={`${id}-from`}
                type="date"
                value={dueFrom}
                onChange={(event) => setDueFrom(event.target.value)}
              />
            </Field>
            <Field label={t("admin.treasury.portfolio.dueTo")} htmlFor={`${id}-to`} className="w-40">
              <Input id={`${id}-to`} type="date" value={dueTo} onChange={(event) => setDueTo(event.target.value)} />
            </Field>
          </Card>

          <Card
            className="flex flex-wrap items-center gap-x-8 gap-y-2 p-3"
            aria-label={t("admin.treasury.list.totals")}
          >
            <dl className="flex flex-wrap gap-x-8 gap-y-2">
              <div>
                <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.treasury.portfolio.count")}</dt>
                <dd className="num text-lg">{totals.data?.count ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.treasury.list.total")}</dt>
                <dd className="num text-lg font-bold">{totals.data ? formatMoney(totals.data.total) : "—"}</dd>
              </div>
              {totals.data && totals.data.overdue_count > 0 && (
                <div>
                  <dt className="text-[0.78rem] font-semibold text-bad">{t("admin.treasury.portfolio.late")}</dt>
                  <dd className="num text-lg font-bold text-bad">
                    {totals.data.overdue_count} · {formatMoney(totals.data.overdue_total)}
                  </dd>
                </div>
              )}
            </dl>
          </Card>

          {effets.isPending ? (
            <p className="text-ink-2">{t("common.loading")}</p>
          ) : rows.length === 0 ? (
            <EmptyState illustration="mix" title={t("admin.treasury.portfolio.empty")}>
              {t(`admin.treasury.portfolio.emptyBody.${tab}`)}
            </EmptyState>
          ) : (
            <Card className="p-2">
              <Table>
                <thead>
                  <tr>
                    {canWrite && STEPS[tab].length > 0 && (
                      <Th className="w-8">
                        <input
                          type="checkbox"
                          aria-label={t("admin.treasury.portfolio.tickAll")}
                          checked={allTicked}
                          onChange={() =>
                            setTicked(allTicked ? {} : Object.fromEntries(rows.map((row) => [row.id, row])))
                          }
                          className="size-4 accent-coral"
                        />
                      </Th>
                    )}
                    <Th>{t("admin.treasury.lines.dueOn")}</Th>
                    <Th>{t("admin.treasury.portfolio.columns.effet")}</Th>
                    <Th>{t("admin.treasury.lines.bank")}</Th>
                    <Th>{t("admin.treasury.portfolio.columns.party")}</Th>
                    <Th className="max-[720px]:hidden">{t("admin.treasury.portfolio.columns.source")}</Th>
                    <Th>{t("admin.treasury.detail.state")}</Th>
                    <Th numeric>{t("admin.payments.columns.amount")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const late = waitingLate(row, today);
                    const party = row.customer ?? row.supplier;
                    return (
                      <tr key={row.id}>
                        {canWrite && STEPS[tab].length > 0 && (
                          <Td>
                            <input
                              type="checkbox"
                              aria-label={t("admin.treasury.portfolio.tick", { number: row.number })}
                              checked={Boolean(ticked[row.id])}
                              onChange={() => toggle(row)}
                              className="size-4 accent-coral"
                            />
                          </Td>
                        )}
                        <Td className={cn("num whitespace-nowrap", late && "font-semibold text-bad")}>
                          {formatDate(row.due_on)}
                        </Td>
                        <Td className="num whitespace-nowrap">
                          {t(`admin.sales.methods.${row.kind}`)} <span className="font-semibold">{row.number}</span>
                        </Td>
                        <Td>{row.bank?.code ?? t("admin.treasury.detail.bankMissing")}</Td>
                        <Td>
                          {party ? (
                            <Link
                              to={row.customer ? `/clients/${row.customer.id}` : `/fournisseurs/${party.id}`}
                              className="hover:underline"
                            >
                              {party.name}
                            </Link>
                          ) : (
                            "—"
                          )}
                          {row.drawer && row.drawer !== party?.name && (
                            <div className="text-[0.8rem] text-ink-2">{row.drawer}</div>
                          )}
                        </Td>
                        <Td className="num max-[720px]:hidden">
                          {row.source_number}
                          {row.deposit && <div className="text-[0.8rem] text-ink-2">{row.deposit.number}</div>}
                        </Td>
                        <Td>
                          <Pill tone={statusTone(row.status)}>{t(`admin.treasury.status.${row.status}`)}</Pill>
                        </Td>
                        <Td numeric className="whitespace-nowrap">
                          {formatMoney(row.amount)}
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
              {(effets.data?.count ?? 0) > PAGE_SIZE && (
                <p className="p-2 text-[0.85rem] text-ink-2">
                  {t("admin.treasury.portfolio.more", { shown: PAGE_SIZE, count: effets.data?.count ?? 0 })}
                </p>
              )}
            </Card>
          )}

          {chosen.length > 0 && (
            <div
              className="sticky bottom-0 z-10 flex flex-wrap items-center gap-3 rounded-card border border-line bg-surface p-3 shadow-md"
              aria-live="polite"
            >
              <span className="font-semibold">
                {t("admin.treasury.portfolio.selection", {
                  count: chosen.length,
                  amount: formatMoney(sum(chosen.map((row) => row.amount))),
                })}
              </span>
              <Button variant="ghost" className="ms-auto" onClick={() => setTicked({})}>
                {t("admin.supplierSettlements.clearSelection")}
              </Button>
              {STEPS[tab].map((one) => (
                <Button
                  key={one}
                  variant={one === STEPS[tab][0] ? "primary" : "secondary"}
                  onClick={() => setStep(one)}
                >
                  {t(`admin.treasury.portfolio.steps.${one}`)}
                </Button>
              ))}
            </div>
          )}
        </>
      )}

      {step && (
        <StepDialog
          step={step}
          effets={chosen}
          banks={banks.data ?? []}
          onClose={() => setStep(null)}
          onDone={() => {
            setStep(null);
            setTicked({});
          }}
        />
      )}
    </>
  );
}

/** The day (and, for a remise, the bank) of the step, a last look at what moves, then "Confirmer". */
function StepDialog({
  step,
  effets,
  banks,
  onClose,
  onDone,
}: {
  step: Step;
  effets: readonly Instrument[];
  banks: readonly { id: number; code: string; name: string }[];
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const id = useId();
  const [day, setDay] = useState(todayInput);
  const [bank, setBank] = useState("");
  const [notes, setNotes] = useState("");
  const [charges, setCharges] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const ids = effets.map((row) => row.id);

  async function confirm() {
    setPending(true);
    setError("");
    try {
      if (step === "deposit") {
        const deposit = await createDeposit({
          instruments: ids,
          bank: bank ? Number(bank) : null,
          deposited_on: day,
          notes: notes.trim(),
        });
        toast.success(t("admin.treasury.portfolio.deposited", { number: deposit.number }));
        void openPdf("bank_deposit", deposit.id);
      } else if (step === "reject") {
        const only = effets[0];
        if (!only || effets.length > 1) throw new Error(t("admin.treasury.portfolio.unpaidOne"));
        await rejectIssuedEffet(only.id, { rejected_on: day, reason: notes.trim() });
        toast.success(t("admin.treasury.portfolio.done.reject", { count: 1 }));
      } else if (step === "unpaid") {
        const only = effets[0];
        if (!only || effets.length > 1) throw new Error(t("admin.treasury.portfolio.unpaidOne"));
        await recordUnpaidEffet(only.id, {
          unpaid_on: day,
          reason: notes.trim(),
          bank_charges: charges.trim().replace(/\s/g, "").replace(",", "."),
        });
        toast.success(t("admin.treasury.portfolio.done.unpaid", { count: 1 }));
      } else {
        const body = { instruments: ids, day, note: notes.trim() };
        if (step === "cash") await cashInstruments(body);
        else if (step === "withdraw") await withdrawInstruments(body);
        else if (step === "return") await returnInstruments(body);
        else await debitInstruments(body);
        toast.success(t(`admin.treasury.portfolio.done.${step}`, { count: ids.length }));
      }
      await queryClient.invalidateQueries({
        predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/"),
      });
      onDone();
    } catch (failure) {
      const found = fieldErrors(failure);
      if (failure instanceof Error && Object.keys(found).length === 0 && !("status" in failure)) {
        setError(failure.message);
        return;
      }
      setError(
        found.bank ??
          found.day ??
          found.reason ??
          found.bank_charges ??
          found.deposited_on ??
          found.instruments ??
          Object.values(found)[0] ??
          t("admin.treasury.portfolio.error"),
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{t(`admin.treasury.portfolio.steps.${step}`)}</DialogTitle>
        <DialogDescription>
          {t("admin.treasury.portfolio.selection", {
            count: effets.length,
            amount: formatMoney(sum(effets.map((row) => row.amount))),
          })}
        </DialogDescription>
        <div className="grid grid-cols-2 gap-3 max-[520px]:grid-cols-1">
          {step === "deposit" && (
            <Field label={t("admin.treasury.portfolio.ourBank")} htmlFor={`${id}-bank`}>
              <Select value={bank} onValueChange={setBank}>
                <SelectTrigger id={`${id}-bank`}>
                  <SelectValue placeholder={t("admin.treasury.lines.bankPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {banks.map((one) => (
                    <SelectItem key={one.id} value={String(one.id)}>
                      {one.code} · {one.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}
          <Field label={t(`admin.treasury.portfolio.days.${step}`)} htmlFor={`${id}-day`}>
            <Input
              id={`${id}-day`}
              type="date"
              max={todayInput()}
              value={day}
              onChange={(event) => setDay(event.target.value)}
            />
          </Field>
          {step === "unpaid" && (
            <>
              <Field
                label={t("admin.treasury.portfolio.unpaidReason")}
                htmlFor={`${id}-reason`}
                className="col-span-full"
              >
                <Input
                  id={`${id}-reason`}
                  value={notes}
                  maxLength={255}
                  placeholder={t("admin.treasury.portfolio.unpaidReasonHint")}
                  onChange={(event) => setNotes(event.target.value)}
                />
              </Field>
              <Field label={t("admin.treasury.portfolio.bankCharges")} htmlFor={`${id}-charges`}>
                <MoneyInput
                  id={`${id}-charges`}
                  inputMode="decimal"
                  value={charges}
                  onChange={(event) => setCharges(event.target.value)}
                  className="num text-end"
                />
              </Field>
              <p className="col-span-full text-[0.85rem] text-ink-2">{t("admin.treasury.portfolio.unpaidBody")}</p>
            </>
          )}
          {step === "reject" && (
            <>
              <Field label={t("admin.treasury.portfolio.unpaidReason")} htmlFor={`${id}-why`} className="col-span-full">
                <Input
                  id={`${id}-why`}
                  value={notes}
                  maxLength={255}
                  onChange={(event) => setNotes(event.target.value)}
                />
              </Field>
              <p className="col-span-full text-[0.85rem] text-ink-2">{t("admin.treasury.portfolio.rejectBody")}</p>
            </>
          )}
          {(step === "deposit" || step === "withdraw") && (
            <Field label={t("admin.supplierPayments.form.notes")} htmlFor={`${id}-notes`} className="col-span-full">
              <Input
                id={`${id}-notes`}
                value={notes}
                maxLength={255}
                onChange={(event) => setNotes(event.target.value)}
              />
            </Field>
          )}
        </div>
        <ul className="flex max-h-48 flex-col gap-1 overflow-auto text-[0.85rem]">
          {effets.map((row) => (
            <li key={row.id} className="num flex justify-between gap-3">
              <span>
                {t(`admin.sales.methods.${row.kind}`)} {row.number} · {row.bank?.code ?? "—"} · {formatDate(row.due_on)}
              </span>
              <span>{formatMoney(row.amount)}</span>
            </li>
          ))}
        </ul>
        {error && (
          <p role="alert" className="text-[0.85rem] font-semibold text-bad">
            {error}
          </p>
        )}
        <DialogFooter className="grid grid-cols-2">
          <Button size="lg" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button size="lg" variant="primary" disabled={pending} onClick={() => void confirm()}>
            {t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
