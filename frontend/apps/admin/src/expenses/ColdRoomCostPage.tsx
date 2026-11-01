import {
  approveElectricityBill,
  type ColdRoomMonth,
  type ColdRoomWeight,
  createElectricityBill,
  deleteElectricityBill,
  type ElectricityBill,
  type PaymentMethodEnum,
  updateColdRoomEstimate,
  updateColdRoomShares,
  updateElectricityBill,
  useGetColdRoomMonth,
  useListColdRoomWeights,
  useListElectricityBills,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  EmptyState,
  Field,
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

import { fromThousandths, toThousandths } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { currentMonth, monthLabel, shiftMonth } from "../hr/shared";
import { CostSelect } from "./CostSelect";
import { ExpensesTabs } from "./ExpensesTabs";
import { canManageCategories, canWriteExpenses, EXPENSE_TONES, PAYMENT_METHODS, refreshExpenses } from "./shared";

type Errors = Record<string, string>;

/** The real invoice of the cold rooms for a finished month (D-227). Saved and approved, it counts as the month's
 * expense at once; saved as a draft it waits, and a draft is edited here until it is approved. */
function BillForm({ month, draft, onDone }: { month: string; draft?: ElectricityBill; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [amount, setAmount] = useState(draft ? draft.amount.replace(".", ",") : "");
  const [method, setMethod] = useState<PaymentMethodEnum>(draft?.payment_method ?? "transfer");
  const [payee, setPayee] = useState(draft?.payee ?? "");
  const [errors, setErrors] = useState<Errors>({});
  const save = useMutation({
    mutationFn: (approve: boolean) => {
      const parsed = parseDecimalInput(amount.trim(), 3);
      if (!parsed || parsed.startsWith("-") || /^0+(\.0+)?$/.test(parsed)) throw new Error("amount");
      const payload = { month, amount: parsed, payment_method: method, payee: payee.trim(), approve_now: approve };
      return draft ? updateElectricityBill(draft.id, payload) : createElectricityBill(payload);
    },
    onSuccess: async (saved) => {
      toast.success(saved.finalized ? t("admin.coldCost.bill.approved") : t("admin.coldCost.bill.saved"));
      await refreshExpenses(queryClient);
      onDone();
    },
    onError: (failure) => {
      if (failure instanceof Error && failure.message === "amount") {
        setErrors({ amount: t("admin.coldCost.bill.amountInvalid") });
        return;
      }
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.coldCost.bill.error") });
    },
  });

  const id = (name: string) => `${formId}-${name}`;
  function submit(approve: boolean) {
    return (event: FormEvent) => {
      event.preventDefault();
      setErrors({});
      save.mutate(approve);
    };
  }
  return (
    <form noValidate onSubmit={submit(false)} className="flex flex-col gap-3">
      <p className="text-ink-2">{t("admin.coldCost.bill.intro")}</p>
      <div className="grid grid-cols-3 gap-4 max-[720px]:grid-cols-1">
        <Field label={t("admin.coldCost.bill.amount")} htmlFor={id("amount")} error={errors.amount}>
          <MoneyInput
            id={id("amount")}
            inputMode="decimal"
            className="num"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            aria-invalid={errors.amount ? true : undefined}
            autoComplete="off"
          />
        </Field>
        <CostSelect
          id={id("method")}
          label={t("admin.coldCost.bill.method")}
          value={method}
          onChange={(value) => setMethod(value as PaymentMethodEnum)}
          options={PAYMENT_METHODS.map((value) => ({ value, label: t(`admin.expenses.methods.${value}`) }))}
          placeholder={t("admin.generalCosts.dialog.choose")}
          error={errors.payment_method}
        />
        <Field label={t("admin.coldCost.bill.payee")} htmlFor={id("payee")} error={errors.payee}>
          <Input id={id("payee")} value={payee} onChange={(event) => setPayee(event.target.value)} autoComplete="off" />
        </Field>
      </div>
      {(errors.detail || errors.month) && (
        <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
          {errors.detail ?? errors.month}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={save.isPending}>
          {t("admin.coldCost.bill.save")}
        </Button>
        <Button type="button" variant="primary" disabled={save.isPending} onClick={submit(true)}>
          {t("admin.coldCost.bill.saveAndApprove")}
        </Button>
      </div>
    </form>
  );
}

/** The bill of the month once typed: its state, and approve / delete while it is a draft. */
function BillSummary({ bill, canWrite }: { bill: ElectricityBill; canWrite: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const approve = useMutation({
    mutationFn: () => approveElectricityBill(bill.id),
    onSuccess: async () => {
      toast.success(t("admin.coldCost.bill.approved"));
      await refreshExpenses(queryClient);
    },
    onError: (failure) => toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.coldCost.bill.error")),
  });
  const remove = useMutation({
    mutationFn: () => deleteElectricityBill(bill.id),
    onSuccess: async () => {
      toast.success(t("admin.coldCost.bill.deleted"));
      await refreshExpenses(queryClient);
    },
    onError: () => toast.error(t("admin.coldCost.bill.error")),
  });
  const draft = bill.status === "draft";
  return (
    <div className="flex flex-col gap-2">
      <p className="flex flex-wrap items-center gap-2">
        <b className="num text-[1.1rem]">{formatMoney(bill.amount)}</b>
        <span className="text-ink-2">{bill.expense_number}</span>
        <Pill tone={EXPENSE_TONES[bill.status]}>{t(`admin.coldCost.bill.statuses.${bill.status}`)}</Pill>
      </p>
      <p className="text-[0.88rem] text-ink-2">
        {draft ? t("admin.coldCost.bill.draftHint") : t("admin.coldCost.bill.approvedHint")}
      </p>
      {draft && canWrite && (
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" disabled={approve.isPending || remove.isPending} onClick={() => approve.mutate()}>
            {t("admin.coldCost.bill.approve")}
          </Button>
          <Button disabled={approve.isPending || remove.isPending} onClick={() => remove.mutate()}>
            {t("admin.coldCost.bill.delete")}
          </Button>
        </div>
      )}
    </div>
  );
}

/** A difference with its sign: "+12,500 DT" when the real bill is higher than the estimate. */
function signedMoney(value: string): string {
  return `${value.startsWith("-") ? "" : "+"}${formatMoney(value)}`;
}

/** The electricity estimate of the month for all the cold rooms (D-227): typed until the month's bill is
 * approved. The lots pay it meanwhile, and the difference with the real bill is booked on them when it is. */
function EstimateForm({ month, data, canWrite }: { month: string; data: ColdRoomMonth; canWrite: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [amount, setAmount] = useState(data.typed_amount ? data.typed_amount.replace(".", ",") : "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const frozen = data.bill?.finalized === true;
  const save = useMutation({
    mutationFn: () => {
      const parsed = parseDecimalInput(amount.trim(), 3);
      if (!parsed || parsed.startsWith("-") || /^0+(\.0+)?$/.test(parsed)) throw new Error("amount");
      return updateColdRoomEstimate({ month, amount: parsed, reason: reason.trim() });
    },
    onSuccess: async () => {
      setError("");
      toast.success(t("admin.coldCost.estimate.saved"));
      await refreshExpenses(queryClient);
    },
    onError: (failure) => {
      if (failure instanceof Error && failure.message === "amount") {
        setError(t("admin.coldCost.estimate.amountInvalid"));
        return;
      }
      setError(Object.values(fieldErrors(failure))[0] ?? t("admin.coldCost.estimate.error"));
    },
  });
  // What the month is estimated at now (or was, once billed).
  const current = data.estimated ? data.total : data.estimate_total;
  const currentText = current !== null ? formatMoney(current) : t("admin.coldCost.rooms.unknown");
  if (frozen || !canWrite) {
    return (
      <p className="text-ink-2">
        {t("admin.coldCost.estimate.current")} <b className="num text-ink">{currentText}</b>
        <span className="block text-[0.88rem]">
          {frozen ? t("admin.coldCost.estimate.frozen") : t("admin.coldCost.estimate.readOnly")}
        </span>
      </p>
    );
  }
  const id = (name: string) => `${formId}-${name}`;
  return (
    <form
      noValidate
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        save.mutate();
      }}
      className="flex flex-col gap-3"
    >
      <p className="text-ink-2">
        {data.estimate_typed ? t("admin.coldCost.estimate.typed") : t("admin.coldCost.estimate.copied")}
      </p>
      <div className="grid grid-cols-2 gap-4 max-[720px]:grid-cols-1">
        <Field label={t("admin.coldCost.estimate.amount")} htmlFor={id("amount")} error={error || undefined}>
          <Input
            id={id("amount")}
            inputMode="decimal"
            className="num"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            aria-invalid={error ? true : undefined}
            autoComplete="off"
          />
        </Field>
        <Field label={t("admin.coldCost.estimate.reason")} htmlFor={id("reason")}>
          <Input
            id={id("reason")}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            autoComplete="off"
          />
        </Field>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {t("admin.coldCost.estimate.save")}
        </Button>
      </div>
    </form>
  );
}

/** The share of each cold room in %: the owner types the percentages, which must add up to 100 (a new cold room
 * is given its part by lowering the others). */
function SharesForm({ rooms, canEdit }: { rooms: ColdRoomWeight[]; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [typed, setTyped] = useState<Record<number, string>>(() =>
    Object.fromEntries(rooms.map((room) => [room.location_id, room.share_percent.replace(".", ",")])),
  );
  const [error, setError] = useState("");
  // Each share as typed, in thousandths of a percent; null while a field is not a positive number.
  const parsed = rooms.map((room) => {
    const value = parseDecimalInput((typed[room.location_id] ?? "").trim(), 3);
    return value && !value.startsWith("-") && toThousandths(value) > 0n ? value : null;
  });
  const total = parsed.reduce<bigint>((all, value) => all + (value ? toThousandths(value) : 0n), 0n);
  const complete = parsed.every((value) => value !== null);
  const valid = complete && total === 100000n;
  const save = useMutation({
    mutationFn: () =>
      updateColdRoomShares({
        shares: rooms.map((room, index) => ({ location_id: room.location_id, percent: parsed[index] ?? "0" })),
      }),
    onSuccess: async () => {
      setError("");
      toast.success(t("admin.coldCost.weights.saved"));
      await refreshExpenses(queryClient);
    },
    onError: (failure) => setError(fieldErrors(failure).shares ?? t("admin.coldCost.weights.invalid")),
  });
  return (
    <>
      <Table>
        <thead>
          <tr>
            <Th>{t("admin.coldCost.rooms.room")}</Th>
            <Th numeric>{t("admin.coldCost.rooms.share")}</Th>
          </tr>
        </thead>
        <tbody>
          {rooms.map((room) => (
            <tr key={room.location_id}>
              <Td className="font-semibold">{room.location_name}</Td>
              <Td numeric>
                {canEdit ? (
                  <span className="inline-flex items-center gap-1">
                    <Input
                      aria-label={t("admin.coldCost.weights.shareOf", { room: room.location_name })}
                      inputMode="decimal"
                      className="num w-24 text-end"
                      value={typed[room.location_id] ?? ""}
                      onChange={(event) => setTyped({ ...typed, [room.location_id]: event.target.value })}
                      autoComplete="off"
                    />
                    %
                  </span>
                ) : (
                  <span className="num">{room.share_percent.replace(".", ",")} %</span>
                )}
              </Td>
            </tr>
          ))}
          <tr>
            <Td className="font-semibold">{t("admin.coldCost.weights.total")}</Td>
            <Td numeric className={valid || !canEdit ? "font-semibold" : "font-semibold text-bad"}>
              {fromThousandths(canEdit ? total : 100000n).replace(".", ",")} %
            </Td>
          </tr>
        </tbody>
      </Table>
      {canEdit && (
        <div className="flex flex-wrap items-center gap-3 p-2">
          {!valid && (
            <span role="status" className="text-[0.85rem] text-bad">
              {t("admin.coldCost.weights.mustBe100")}
            </span>
          )}
          {error && <span className="text-[0.85rem] text-bad">{error}</span>}
          <Button
            variant="primary"
            className="ms-auto"
            disabled={!valid || save.isPending}
            onClick={() => save.mutate()}
          >
            {t("admin.coldCost.weights.save")}
          </Button>
        </div>
      )}
    </>
  );
}

/** "Chambres froides : coût": the month's electricity bill, what each room costs per day (estimated until the
 * bill is approved) and the weight of each room (P5-T02, D-058). */
export function ColdRoomCostPage() {
  const { t, i18n } = useTranslation();
  const session = useOutletContext<Session>();
  const canWrite = canWriteExpenses(session);
  const isOwner = canManageCategories(session);
  const [month, setMonth] = useState(() => shiftMonth(currentMonth(), -1));
  const view = useGetColdRoomMonth({ month });
  const weights = useListColdRoomWeights();
  const bills = useListElectricityBills();
  const [reload, setReload] = useState(0);
  const finished = month < currentMonth();
  const label = monthLabel(month, i18n.language);
  const data = view.data;

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.finance")} title={t("admin.coldCost.title")} />
      <ExpensesTabs />
      <p className="text-ink-2">{t("admin.coldCost.intro")}</p>
      {!canWrite && <p className="text-[0.88rem] text-ink-2">{t("admin.coldCost.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-2 p-3">
        <span className="me-auto font-semibold">{t("admin.coldCost.monthNav")}</span>
        <Button
          variant="ghost"
          aria-label={t("admin.coldCost.previous")}
          onClick={() => setMonth(shiftMonth(month, -1))}
        >
          ‹
        </Button>
        <b className="min-w-36 text-center capitalize" aria-live="polite">
          {label}
        </b>
        <Button
          variant="ghost"
          aria-label={t("admin.coldCost.next")}
          disabled={month >= currentMonth()}
          onClick={() => setMonth(shiftMonth(month, 1))}
        >
          ›
        </Button>
      </Card>

      <section aria-labelledby="cold-estimate" className="flex flex-col gap-2">
        <h2 id="cold-estimate">{t("admin.coldCost.estimate.title", { month: label })}</h2>
        <p className="text-ink-2">{t("admin.coldCost.estimate.body")}</p>
        <Card className="flex flex-col gap-3 p-4">
          {data && (
            <EstimateForm key={`${month}-${data.typed_amount ?? ""}`} month={month} data={data} canWrite={canWrite} />
          )}
        </Card>
      </section>

      <section aria-labelledby="cold-bill" className="flex flex-col gap-2">
        <h2 id="cold-bill">{t("admin.coldCost.bill.title", { month: label })}</h2>
        <Card className="flex flex-col gap-3 p-4">
          {view.isPending ? (
            <p className="text-ink-2">{t("common.loading")}</p>
          ) : !data ? (
            <p role="alert" className="text-bad">
              {t("common.serverUnreachable")}
            </p>
          ) : data.bill ? (
            <>
              <BillSummary key={`${data.bill.id}-${data.bill.status}-${reload}`} bill={data.bill} canWrite={canWrite} />
              {data.bill.status === "draft" && canWrite && (
                <BillForm
                  key={`draft-${data.bill.id}-${reload}`}
                  month={month}
                  draft={data.bill}
                  onDone={() => setReload(reload + 1)}
                />
              )}
            </>
          ) : !finished ? (
            <p className="text-ink-2">{t("admin.coldCost.bill.notYet")}</p>
          ) : canWrite ? (
            <BillForm key={month} month={month} onDone={() => setReload(reload + 1)} />
          ) : (
            <p className="text-ink-2">{t("admin.coldCost.bill.none")}</p>
          )}
        </Card>
      </section>

      <section aria-labelledby="cold-rooms" className="flex flex-col gap-2">
        <h2 id="cold-rooms">{t("admin.coldCost.rooms.title")}</h2>
        {data && data.rooms.length === 0 ? (
          <EmptyState illustration="fridge" title={t("admin.coldCost.rooms.noRooms")}>
            {t("admin.coldCost.rooms.noRoomsBody")}
          </EmptyState>
        ) : (
          data && (
            <Card className="p-2">
              <Table>
                <thead>
                  <tr>
                    <Th>{t("admin.coldCost.rooms.room")}</Th>
                    <Th numeric>{t("admin.coldCost.rooms.weight")}</Th>
                    <Th numeric>{t("admin.coldCost.rooms.month")}</Th>
                    <Th numeric>{t("admin.coldCost.rooms.day")}</Th>
                    <Th>{t("admin.coldCost.rooms.kind")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.rooms.map((row) => (
                    <tr key={row.location_id}>
                      <Td className="font-semibold">{row.location_name}</Td>
                      <Td numeric className="num">
                        {row.weight.replace(".", ",")}
                      </Td>
                      <Td numeric className="whitespace-nowrap">
                        {row.month_amount !== null ? formatMoney(row.month_amount) : t("admin.coldCost.rooms.unknown")}
                      </Td>
                      <Td numeric className="whitespace-nowrap">
                        {row.day_amount !== null ? formatMoney(row.day_amount) : t("admin.coldCost.rooms.unknown")}
                      </Td>
                      <Td>
                        <Pill tone={row.estimated ? "warn" : "good"}>
                          {row.estimated ? t("admin.coldCost.rooms.estimated") : t("admin.coldCost.rooms.real")}
                        </Pill>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <div className="flex flex-col items-end gap-1 border-t border-line px-2.5 py-3">
                {data.estimated ? (
                  <p>
                    {t("admin.coldCost.rooms.total")}{" "}
                    <b className="num">
                      {data.total !== null ? formatMoney(data.total) : t("admin.coldCost.rooms.unknown")}
                    </b>
                  </p>
                ) : (
                  <>
                    <p>
                      {t("admin.coldCost.rooms.estimateTotal")}{" "}
                      <b className="num">
                        {data.estimate_total !== null
                          ? formatMoney(data.estimate_total)
                          : t("admin.coldCost.rooms.unknown")}
                      </b>
                    </p>
                    <p>
                      {t("admin.coldCost.rooms.realTotal")}{" "}
                      <b className="num">
                        {data.total !== null ? formatMoney(data.total) : t("admin.coldCost.rooms.unknown")}
                      </b>
                    </p>
                    <p>
                      {t("admin.coldCost.rooms.difference")}{" "}
                      <b className="num">
                        {data.difference !== null ? signedMoney(data.difference) : t("admin.coldCost.rooms.unknown")}
                      </b>
                    </p>
                  </>
                )}
              </div>
              {data.estimated && (
                <p className="px-2.5 pb-2 text-[0.85rem] text-ink-2">
                  {data.estimate_typed
                    ? t("admin.coldCost.rooms.estimateTyped")
                    : data.estimate_source_month
                      ? t("admin.coldCost.rooms.estimateFrom", {
                          month: monthLabel(data.estimate_source_month, i18n.language),
                        })
                      : t("admin.coldCost.rooms.noEstimate")}
                </p>
              )}
            </Card>
          )
        )}
      </section>

      <section aria-labelledby="cold-weights" className="flex flex-col gap-2">
        <h2 id="cold-weights">{t("admin.coldCost.weights.title")}</h2>
        <p className="text-ink-2">{t("admin.coldCost.weights.body")}</p>
        {!isOwner && <p className="text-[0.85rem] text-ink-2">{t("admin.coldCost.weights.ownerOnly")}</p>}
        <Card className="p-2">
          {weights.data && (
            <SharesForm
              key={weights.data.map((room) => `${room.location_id}:${room.weight}`).join(",")}
              rooms={weights.data}
              canEdit={isOwner}
            />
          )}
        </Card>
      </section>

      <section aria-labelledby="cold-bills" className="flex flex-col gap-2">
        <CardTitle id="cold-bills" className="text-[1rem]">
          {t("admin.coldCost.bills.title")}
        </CardTitle>
        {(bills.data ?? []).length === 0 ? (
          <p className="text-ink-2">{t("admin.coldCost.bills.empty")}</p>
        ) : (
          <Card className="p-2">
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.coldCost.bills.month")}</Th>
                  <Th numeric>{t("admin.coldCost.bills.amount")}</Th>
                  <Th>{t("admin.coldCost.bills.status")}</Th>
                </tr>
              </thead>
              <tbody>
                {(bills.data ?? []).map((bill) => (
                  <tr key={bill.id}>
                    <Td className="capitalize">
                      <button type="button" className="text-sea hover:underline" onClick={() => setMonth(bill.month)}>
                        {monthLabel(bill.month, i18n.language)}
                      </button>
                    </Td>
                    <Td numeric className="whitespace-nowrap">
                      {formatMoney(bill.amount)}
                    </Td>
                    <Td>
                      <Pill tone={EXPENSE_TONES[bill.status]}>{t(`admin.coldCost.bill.statuses.${bill.status}`)}</Pill>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        )}
      </section>
    </>
  );
}
