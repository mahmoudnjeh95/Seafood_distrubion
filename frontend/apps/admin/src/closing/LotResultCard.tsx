import {
  closeLot,
  type ComputedResult,
  type LotResultView,
  reopenLot,
  type ResultCostGroup,
  type ResultStep,
  useGetLotResult,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatDateTime, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
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
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId, useState } from "react";
import { Link } from "react-router";

import { fieldErrors } from "../lib/errors";
import { canWriteResults, formatRate, refreshLotResult } from "../partnerships/shared";

const KNOWN_KINDS = new Set([
  "lot",
  "truck_day",
  "employee",
  "cold_room",
  "cold_room_adjustment",
  "general",
  "customer_write_off",
  "supplier_write_off",
]);
type KnownKind =
  | "lot"
  | "truck_day"
  | "employee"
  | "cold_room"
  | "cold_room_adjustment"
  | "general"
  | "customer_write_off"
  | "supplier_write_off";

const OUTCOME_TONE = { profit: "good", zero: "neutral", loss: "bad" } as const;

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className="num font-semibold">{children}</dd>
    </div>
  );
}

function ErrorLine({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
      {message}
    </p>
  );
}

/** One line of the explanation: what it is, its sign and amount, and what lies behind it when opened. */
function StepRow({
  label,
  sign,
  amount,
  total,
  children,
}: {
  label: string;
  sign: string;
  amount: string;
  total?: boolean;
  children?: ReactNode;
}) {
  const figure = (
    <span className={`num whitespace-nowrap ${total ? "font-bold" : ""}`}>
      {sign === "-" ? "− " : sign === "+" ? "+ " : ""}
      {formatMoney(amount)}
    </span>
  );
  if (!children) {
    return (
      <div className={`flex items-baseline gap-3 px-2.5 py-2 ${total ? "border-t border-line" : ""}`}>
        <span className={`me-auto ${total ? "font-bold" : ""}`}>{label}</span>
        {figure}
      </div>
    );
  }
  return (
    <details className="group px-2.5 py-2">
      <summary className="flex cursor-pointer list-none items-baseline gap-3">
        <span className="me-auto">
          {label} <span className="text-[0.8rem] text-sea group-open:hidden">▸</span>
          <span className="hidden text-[0.8rem] text-sea group-open:inline">▾</span>
        </span>
        {figure}
      </summary>
      <ul className="mt-2 flex flex-col gap-1 border-s-2 border-line ps-3 text-[0.88rem]">{children}</ul>
    </details>
  );
}

function Line({ children, amount }: { children: ReactNode; amount: string }) {
  return (
    <li className="flex items-baseline gap-3">
      <span className="me-auto">{children}</span>
      <span className="num whitespace-nowrap text-ink-2">{formatMoney(amount)}</span>
    </li>
  );
}

function CostLines({ group }: { group: ResultCostGroup }) {
  return group.lines.map((line, index) => {
    const to =
      line.source_type === "expense" && line.source_id
        ? `/charges/${line.source_id}`
        : line.source_type === "employee" && line.source_id
          ? `/salaires/employes/${line.source_id}`
          : null;
    const name = line.reference ? `${line.reference} · ${line.title}` : line.title;
    return (
      <Line key={`${line.source_type}-${line.source_id}-${index}`} amount={line.amount}>
        <span className="num text-ink-2">{formatDate(line.on)}</span>{" "}
        {to ? (
          <Link to={to} className="font-semibold text-sea hover:underline">
            {name}
          </Link>
        ) : (
          name
        )}
        {line.description && <span className="text-ink-2"> · {line.description}</span>}
        {line.detail && <span className="text-ink-2"> · {line.detail}</span>}
      </Line>
    );
  });
}

function Explanation({ result }: { result: ComputedResult }) {
  const { t } = useTranslation();
  const partnerName = result.partner?.partner_name ?? "";
  const groups = new Map(result.cost_groups.map((group) => [group.kind, group]));

  function costLabel(kind: string) {
    return KNOWN_KINDS.has(kind)
      ? t(`admin.lotResult.costKinds.${kind as KnownKind}`)
      : t("admin.lotResult.costKinds.other", { kind });
  }

  function row(step: ResultStep, index: number) {
    const key = `${step.code}-${step.kind}-${index}`;
    switch (step.code) {
      case "revenue":
        return (
          <StepRow
            key={key}
            label={t("admin.lotResult.steps.revenue", { quantity: formatQuantity(result.quantity_sold) })}
            sign={step.sign}
            amount={step.amount}
          >
            {result.sales.length > 0 &&
              result.sales.map((sale, row) => (
                <Line key={`${sale.sale_id}-${row}`} amount={sale.revenue}>
                  <Link to={`/ventes/${sale.sale_id}`} className="font-semibold text-sea hover:underline">
                    {t("admin.lotResult.lines.sale", { number: sale.sale_number, customer: sale.customer })}
                  </Link>{" "}
                  <span className="text-ink-2">
                    {formatDate(sale.sold_on)} ·{" "}
                    {t("admin.lotResult.lines.saleDetail", {
                      quantity: formatQuantity(sale.quantity),
                      price: formatMoney(sale.unit_price),
                    })}
                  </span>
                </Line>
              ))}
          </StepRow>
        );
      case "cogs":
        return (
          <StepRow key={key} label={t("admin.lotResult.steps.cogs")} sign={step.sign} amount={step.amount}>
            {result.sales.length > 0 &&
              result.sales.map((sale, row) => (
                <Line key={`${sale.sale_id}-${row}`} amount={sale.cost}>
                  <Link to={`/ventes/${sale.sale_id}`} className="font-semibold text-sea hover:underline">
                    {t("admin.lotResult.lines.sale", { number: sale.sale_number, customer: sale.customer })}
                  </Link>{" "}
                  <span className="text-ink-2">
                    {formatDate(sale.sold_on)} ·{" "}
                    {t("admin.lotResult.lines.cogsDetail", { quantity: formatQuantity(sale.quantity) })}
                  </span>
                </Line>
              ))}
          </StepRow>
        );
      case "spoilage":
        return (
          <StepRow
            key={key}
            label={t("admin.lotResult.steps.spoilage", { quantity: formatQuantity(result.quantity_written_off) })}
            sign={step.sign}
            amount={step.amount}
          >
            {result.stock_rows.length > 0 &&
              result.stock_rows.map((stockRow) => (
                <Line key={stockRow.movement_id} amount={stockRow.value}>
                  <span className="num text-ink-2">{formatDate(stockRow.occurred_on)}</span>{" "}
                  {t(
                    `admin.lotResult.lines.${stockRow.kind === "count_correction" || stockRow.kind === "adjustment" ? stockRow.kind : "loss"}`,
                  )}{" "}
                  <span className="text-ink-2">
                    {t("admin.lotResult.lines.lossDetail", {
                      quantity: formatQuantity(stockRow.quantity),
                      cost: formatMoney(stockRow.unit_cost),
                    })}
                    {stockRow.reason && ` · ${stockRow.reason}`}
                  </span>
                </Line>
              ))}
          </StepRow>
        );
      case "cost": {
        const group = groups.get(step.kind);
        return (
          <StepRow key={key} label={costLabel(step.kind)} sign={step.sign} amount={step.amount}>
            {group && <CostLines group={group} />}
          </StepRow>
        );
      }
      case "net_result":
        return <StepRow key={key} label={t("admin.lotResult.steps.net_result")} sign="" amount={step.amount} total />;
      case "partner_share":
        return (
          <StepRow
            key={key}
            label={
              step.rate
                ? t("admin.lotResult.steps.partner_share", { name: partnerName, rate: formatRate(step.rate) })
                : t("admin.lotResult.steps.partner_share_zero", { name: partnerName })
            }
            sign=""
            amount={step.amount}
          />
        );
      case "owner_share":
        return <StepRow key={key} label={t("admin.lotResult.steps.owner_share")} sign="" amount={step.amount} />;
      case "partner_capital":
      case "capital_deducted":
      case "capital_to_return":
      case "profit_share":
      case "payable_to_partner":
      case "uncovered_loss":
        return (
          <StepRow
            key={key}
            label={t(`admin.lotResult.steps.${step.code}`, { name: partnerName })}
            sign={step.code === "capital_to_return" || step.code === "payable_to_partner" ? "" : step.sign}
            amount={step.amount}
            total={step.code === "payable_to_partner"}
          />
        );
      default:
        return <StepRow key={key} label={step.code} sign={step.sign} amount={step.amount} />;
    }
  }

  const resultSteps = result.steps.filter((step) => !step.code.startsWith("partner") && !isPartnerStep(step));
  const partnerSteps = result.steps.filter((step) => step.code.startsWith("partner") || isPartnerStep(step));
  return (
    <>
      <div className="flex flex-col divide-y divide-line/60">{resultSteps.map(row)}</div>
      {result.partner ? (
        <div className="flex flex-col gap-1">
          <h3 className="px-2.5 text-[0.95rem]">{t("admin.lotResult.partnerTitle", { name: partnerName })}</h3>
          <div className="flex flex-col divide-y divide-line/60">{partnerSteps.map(row)}</div>
        </div>
      ) : (
        <p className="px-2.5 text-[0.88rem] text-ink-2">{t("admin.lotResult.noPartner")}</p>
      )}
    </>
  );
}

const PARTNER_STEPS = new Set([
  "owner_share",
  "capital_deducted",
  "capital_to_return",
  "profit_share",
  "payable_to_partner",
  "uncovered_loss",
]);
function isPartnerStep(step: ResultStep) {
  return PARTNER_STEPS.has(step.code);
}

function Checks({ view }: { view: LotResultView }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-1.5">
      <h3 className="text-[0.95rem]">{t("admin.lotResult.checks.title")}</h3>
      <ul className="flex flex-col gap-1 text-[0.9rem]">
        {view.checks.map((check) => {
          const code = check.code as "stock_empty" | "costs_approved" | "customers_paid";
          const text = check.ok
            ? t(`admin.lotResult.checks.${code}`)
            : t(`admin.lotResult.checks.${code}Failed`, {
                quantity: formatQuantity(check.quantity ?? "0"),
                count: check.count ?? 0,
                amount: formatMoney(check.amount ?? "0"),
              });
          return (
            <li key={check.code} className="flex items-center gap-2">
              <Pill tone={check.ok ? "good" : check.blocking ? "bad" : "warn"}>{check.ok ? "✓" : "!"}</Pill>
              <span>{text}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function CloseDialog({ batchId, number, onDone }: { batchId: number; number: string; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [confirmed, setConfirmed] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const close = useMutation({
    mutationFn: () => closeLot(batchId, { costs_confirmed: confirmed }),
    onSuccess: async () => {
      toast.success(t("admin.lotResult.closedToast"));
      await refreshLotResult(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.lotResult.closeError") });
    },
  });
  return (
    <DialogContent className="w-[min(500px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.lotResult.closeTitle", { number })}</DialogTitle>
      <DialogDescription>{t("admin.lotResult.closeDescription")}</DialogDescription>
      <form
        id={formId}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          close.mutate();
        }}
      >
        <label className="flex items-center gap-2 font-semibold">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          {t("admin.lotResult.costsConfirmed")}
        </label>
      </form>
      <ErrorLine message={errors.costs_confirmed ?? errors.detail} />
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.lotResult.back")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={close.isPending || !confirmed}>
          {close.isPending ? t("admin.lotResult.closing") : t("admin.lotResult.confirmClose")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function ReopenDialog({ batchId, number, onDone }: { batchId: number; number: string; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const reopen = useMutation({
    mutationFn: () => reopenLot(batchId, { reason: reason.trim() }),
    onSuccess: async () => {
      toast.success(t("admin.lotResult.reopenedToast"));
      await refreshLotResult(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.lotResult.reopenError") });
    },
  });
  return (
    <DialogContent className="w-[min(500px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.lotResult.reopenTitle", { number })}</DialogTitle>
      <DialogDescription>{t("admin.lotResult.reopenDescription")}</DialogDescription>
      <form
        id={formId}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          reopen.mutate();
        }}
      >
        <Field label={t("admin.lotResult.reason")} htmlFor={`${formId}-reason`} error={errors.reason}>
          <Input id={`${formId}-reason`} value={reason} onChange={(event) => setReason(event.target.value)} />
        </Field>
      </form>
      <ErrorLine message={errors.detail} />
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.lotResult.back")}</Button>
        <Button type="submit" form={formId} variant="danger" disabled={reopen.isPending}>
          {t("admin.lotResult.confirmReopen")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

/** "Résultat du lot" (P6-T02, D-061): the lot's result step by step, with what lies behind each number.
 * Live ("so far") while the lot is open, frozen once it is closed; the owner closes and reopens it. */
export function LotResultCard({ batchId, session }: { batchId: number; session: Session }) {
  const { t } = useTranslation();
  const view = useGetLotResult(batchId, { query: { enabled: Number.isInteger(batchId) && batchId > 0 } });
  const [dialog, setDialog] = useState<"close" | "reopen" | null>(null);
  const canWrite = canWriteResults(session);
  const data = view.data;
  const result = data?.result;

  return (
    <section aria-labelledby="lot-result" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="lot-result" className="me-auto">
          {t("admin.lotResult.title")}
        </h2>
        {canWrite && data?.state === "open" && (
          <Button variant="primary" disabled={!data.can_close} onClick={() => setDialog("close")}>
            {t("admin.lotResult.close")}
          </Button>
        )}
        {canWrite && data?.state === "closed" && (
          <Button onClick={() => setDialog("reopen")}>{t("admin.lotResult.reopen")}</Button>
        )}
      </div>
      <Card className="flex flex-col gap-4 p-4">
        {view.isPending ? (
          <p className="text-ink-2">{t("common.loading")}</p>
        ) : !data || !result ? (
          <p role="alert" className="text-bad">
            {t("admin.lotResult.loadError")}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone={OUTCOME_TONE[result.outcome]}>{t(`admin.lotResult.outcomes.${result.outcome}`)}</Pill>
              <span className="text-[0.88rem] text-ink-2">
                {data.state === "closed" && data.closing
                  ? t("admin.lotResult.closed", {
                      date: formatDateTime(data.closing.closed_at),
                      name: data.closing.closed_by_name,
                    })
                  : t("admin.lotResult.open")}
              </span>
            </div>
            <dl className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(8rem,1fr))]">
              <Fact label={t("admin.lotResult.facts.received")}>{formatQuantity(result.batch.received_quantity)}</Fact>
              <Fact label={t("admin.lotResult.facts.sold")}>{formatQuantity(result.quantity_sold)}</Fact>
              <Fact label={t("admin.lotResult.facts.writtenOff")}>{formatQuantity(result.quantity_written_off)}</Fact>
              <Fact label={t("admin.lotResult.facts.onHand")}>{formatQuantity(result.batch.on_hand_quantity)}</Fact>
            </dl>
            {result.batch.on_hand_quantity !== "0.000" && (
              <p className="text-[0.85rem] text-ink-2">
                {t("admin.lotResult.facts.stockValue")} : <span className="num">{formatMoney(result.stock_value)}</span>
              </p>
            )}
            <dl className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(8rem,1fr))]">
              <Fact label={t("admin.lotResult.summary.revenue")}>{formatMoney(result.revenue)}</Fact>
              <Fact label={t("admin.lotResult.summary.costs")}>{formatMoney(result.costs_total)}</Fact>
              <Fact label={t("admin.lotResult.summary.net")}>{formatMoney(result.net_result)}</Fact>
              <Fact
                label={
                  result.partner
                    ? t("admin.lotResult.summary.partnerShare", { name: result.partner.partner_name })
                    : t("admin.lotResult.summary.ownerShare")
                }
              >
                {formatMoney(result.partner ? result.partner.share : result.owner_share)}
              </Fact>
            </dl>
            <Explanation result={result} />
            {data.state === "closed" &&
              data.live_net_result !== null &&
              data.live_net_result !== undefined &&
              data.live_net_result !== result.net_result && (
                <p className="rounded-chip bg-warn-soft px-3 py-2 text-[0.88rem] text-warn">
                  {t("admin.lotResult.drift", { amount: formatMoney(data.live_net_result) })}
                </p>
              )}
            <Checks view={data} />
            {data.checks.some((check) => check.code === "customers_paid" && !check.ok) && (
              <p className="text-[0.85rem] text-ink-2">{t("admin.lotResult.paymentsWarning")}</p>
            )}
            {data.history.length > 0 && (
              <div className="flex flex-col gap-1 text-[0.85rem] text-ink-2">
                <h3 className="text-[0.95rem] text-ink">{t("admin.lotResult.history")}</h3>
                {data.history.map((closing) => (
                  <p key={closing.id}>
                    {t("admin.lotResult.historyLine", {
                      closed: formatDateTime(closing.closed_at),
                      reopened: closing.reopened_at ? formatDateTime(closing.reopened_at) : "",
                      name: closing.reopened_by_name,
                      reason: closing.reopen_reason,
                    })}
                  </p>
                ))}
              </div>
            )}
          </>
        )}
      </Card>
      <Dialog open={dialog !== null} onOpenChange={(open) => !open && setDialog(null)}>
        {dialog === "close" && result && (
          <CloseDialog batchId={batchId} number={result.batch.batch_number} onDone={() => setDialog(null)} />
        )}
        {dialog === "reopen" && result && (
          <ReopenDialog batchId={batchId} number={result.batch.batch_number} onDone={() => setDialog(null)} />
        )}
      </Dialog>
    </section>
  );
}
