import {
  cancelSupplierPlanLine,
  type ListSupplierSettlementsState,
  type ListSupplierSettlementsType,
  type PlanLine,
  type SettlementRow,
  type SettlementRowStateEnum,
  useListSupplierSettlements,
  useListSuppliers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  ConfirmButton,
  cn,
  EmptyState,
  PageHeader,
  Pill,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useNavigate, useOutletContext, useSearchParams } from "react-router";

import { canRecordReceipts, todayInTunis } from "../receipts/shared";
import { PlanDialog } from "./PlanDialog";
import { refreshPurchasing } from "./shared";

const TABS: readonly ListSupplierSettlementsState[] = ["undefined", "planned", "overdue", "settled"];
const TYPES: readonly ListSupplierSettlementsType[] = ["port", "office", "opening"];
const ALL = "all";

const STATE_TONE: Record<SettlementRowStateEnum, "good" | "sea" | "bad" | "warn"> = {
  settled: "good",
  planned: "sea",
  overdue: "bad",
  undefined: "warn",
};

function Figure({ label, children, tone }: { label: string; children: ReactNode; tone?: "bad" | "warn" }) {
  return (
    <Card className="flex flex-col gap-1">
      <span className="text-[0.8rem] font-semibold text-ink-2">{label}</span>
      <span className={cn("num text-[1.3rem] font-bold", tone === "bad" && "text-bad", tone === "warn" && "text-warn")}>
        {children}
      </span>
    </Card>
  );
}

/** "Règlements fournisseurs" (D-192): per supplier invoice, what is paid, planned, or still to define. */
export function SupplierSettlementsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canEdit = canRecordReceipts(session);
  const [params, setParams] = useSearchParams();
  const requested = params.get("etat");
  const state = TABS.find((tab) => tab === requested) ?? "undefined";
  const type = TYPES.find((one) => one === params.get("type"));
  const supplierId = Number(params.get("fournisseur")) || undefined;
  const [editing, setEditing] = useState<SettlementRow | null>(null);
  const today = todayInTunis();

  const suppliers = useListSuppliers({ status: "all" });
  const list = useListSupplierSettlements({ state, type, supplier: supplierId });

  const setParam = (name: string, value: string | undefined) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value) next.set(name, value);
        else next.delete(name);
        return next;
      },
      { replace: true },
    );

  const cancel = useMutation({
    mutationFn: (lineId: number) => cancelSupplierPlanLine(lineId),
    onSuccess: async () => {
      toast.success(t("admin.supplierSettlements.cancelled"));
      await refreshPurchasing(queryClient);
    },
    onError: () => toast.error(t("admin.supplierSettlements.cancelError")),
  });

  const pay = (row: SettlementRow, line: PlanLine) => {
    const query = new URLSearchParams({
      fournisseur: String(row.supplier.id),
      facture: String(row.invoice_id),
      ligne: String(line.id),
      montant: line.amount,
      mode: line.method,
    });
    if (line.reference) query.set("ref", line.reference);
    if (line.cash_on) query.set("encaisse", line.cash_on);
    void navigate(`/achats/paiements/nouveau?${query.toString()}`);
  };

  const header = (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.supplierSettlements.title")} />
      <p className="text-ink-2">{t("admin.supplierSettlements.intro")}</p>
    </>
  );
  if (list.isPending)
    return (
      <>
        {header}
        <p className="text-ink-2">{t("common.loading")}</p>
      </>
    );
  if (!list.data) {
    return (
      <>
        {header}
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      </>
    );
  }
  const { rows, summary } = list.data;
  const totalDue = [summary.paid, summary.planned, summary.undefined].reduce((a, b) => a + Number(b), 0);

  return (
    <>
      {header}
      <div className="grid grid-cols-4 gap-3 max-[900px]:grid-cols-2">
        <Figure label={t("admin.supplierSettlements.totalDue")}>
          {formatMoney(totalDue.toFixed(3))}
          {Number(summary.overdue) > 0 && (
            <span className="block text-[0.78rem] font-semibold text-bad">
              {t("admin.supplierSettlements.ofWhichOverdue", { amount: formatMoney(summary.overdue) })}
            </span>
          )}
        </Figure>
        <Figure label={t("admin.supplierSettlements.paid")}>{formatMoney(summary.paid)}</Figure>
        <Figure label={t("admin.supplierSettlements.planned")}>{formatMoney(summary.planned)}</Figure>
        <Figure
          label={t("admin.supplierSettlements.undefined")}
          tone={Number(summary.undefined) > 0 ? "warn" : undefined}
        >
          {formatMoney(summary.undefined)}
        </Figure>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <nav
          aria-label={t("admin.supplierSettlements.tabs")}
          className="flex w-fit flex-wrap rounded-control bg-surface-2 p-1"
        >
          {TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              aria-current={tab === state ? "page" : undefined}
              onClick={() => setParam("etat", tab === "undefined" ? undefined : tab)}
              className={cn(
                "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
                tab === state && "bg-surface text-ink shadow-card",
              )}
            >
              {t(`admin.supplierSettlements.tab.${tab}`)}{" "}
              <span className="num text-[0.78rem]">({summary.counts[tab]})</span>
            </button>
          ))}
        </nav>
        <Select value={type ?? ALL} onValueChange={(value) => setParam("type", value === ALL ? undefined : value)}>
          <SelectTrigger className="w-auto min-w-44" aria-label={t("admin.supplierSettlements.typeFilter")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t("admin.supplierSettlements.allTypes")}</SelectItem>
            {TYPES.map((one) => (
              <SelectItem key={one} value={one}>
                {t(`admin.supplierSettlements.type.${one}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={supplierId ? String(supplierId) : ALL}
          onValueChange={(value) => setParam("fournisseur", value === ALL ? undefined : value)}
        >
          <SelectTrigger className="w-auto min-w-44" aria-label={t("admin.supplierSettlements.supplierFilter")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t("admin.supplierSettlements.allSuppliers")}</SelectItem>
            {(suppliers.data ?? []).map((one) => (
              <SelectItem key={one.id} value={String(one.id)}>
                {one.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {rows.length === 0 ? (
        <EmptyState illustration="fish" title={t("admin.supplierSettlements.empty")}>
          {t(`admin.supplierSettlements.emptyBody.${state}`)}
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-3">
          {rows.map((row) => {
            const open = row.plan_lines.filter((line) => line.status === "open");
            const canDefine = canEdit && row.state !== "settled";
            return (
              <Card key={row.invoice_id} className="flex flex-col gap-3">
                <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
                  <div className="min-w-0 flex-1">
                    <Link to={`/fournisseurs/${row.supplier.id}`} className="font-semibold hover:underline">
                      {row.supplier.name}
                    </Link>
                    <div className="text-[0.85rem] text-ink-2">
                      <Link to={`/achats/factures/${row.invoice_id}`} className="num hover:underline">
                        {row.field_purchase_number ?? row.number}
                      </Link>
                      {" · "}
                      {t(`admin.supplierSettlements.type.${row.purchase_type}`)}
                      {row.supplier_reference && <span className="num"> · {row.supplier_reference}</span>}
                    </div>
                    <div className="text-[0.8rem] text-ink-2">
                      {t("admin.supplierSettlements.dates", {
                        date: formatDate(row.invoice_date),
                        due: formatDate(row.due_date),
                      })}
                    </div>
                  </div>
                  <Pill tone={STATE_TONE[row.state]}>{t(`admin.supplierSettlements.state.${row.state}`)}</Pill>
                </div>

                <dl className="grid grid-cols-4 gap-3 max-[640px]:grid-cols-2">
                  <Amount label={t("admin.supplierSettlements.columns.total")} value={row.total} bold />
                  <Amount label={t("admin.supplierSettlements.columns.paid")} value={row.paid} />
                  <Amount label={t("admin.supplierSettlements.columns.planned")} value={row.planned} />
                  <Amount
                    label={t("admin.supplierSettlements.columns.undefined")}
                    value={row.undefined}
                    tone={Number(row.undefined) > 0 ? "warn" : undefined}
                  />
                </dl>

                {open.length > 0 && (
                  <ul className="flex flex-col gap-2 border-t border-line pt-2">
                    {open.map((line) => (
                      <li key={line.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.88rem]">
                        <span className="num font-semibold">{formatMoney(line.amount)}</span>
                        <span>{t(`admin.supplierPayments.method.${line.method}`)}</span>
                        {line.reference && <span className="num text-ink-2">{line.reference}</span>}
                        <span className={cn("num", line.planned_on < today ? "font-semibold text-bad" : "text-ink-2")}>
                          {t("admin.supplierSettlements.plannedOn", { date: formatDate(line.planned_on) })}
                        </span>
                        {line.cash_on && (
                          <span className="num text-ink-2">
                            {t("admin.supplierSettlements.cashOn", { date: formatDate(line.cash_on) })}
                          </span>
                        )}
                        {canEdit && (
                          <span className="ms-auto flex gap-2">
                            <Button onClick={() => pay(row, line)}>
                              {t("admin.supplierSettlements.recordPayment")}
                            </Button>
                            <ConfirmButton
                              variant="ghost"
                              title={t("admin.supplierSettlements.cancelTitle")}
                              rows={[[t("admin.supplierSettlements.columns.total"), formatMoney(line.amount)]]}
                              onConfirm={() => cancel.mutate(line.id)}
                            >
                              {t("admin.supplierSettlements.cancelLine")}
                            </ConfirmButton>
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}

                {canDefine && (
                  <div>
                    <Button
                      variant={row.state === "undefined" ? "primary" : "secondary"}
                      onClick={() => setEditing(row)}
                    >
                      {t("admin.supplierSettlements.define")}
                    </Button>
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {editing && <PlanDialog row={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function Amount({ label, value, bold, tone }: { label: string; value: string; bold?: boolean; tone?: "warn" }) {
  return (
    <div>
      <dt className="text-[0.75rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("num whitespace-nowrap", bold && "font-bold", tone === "warn" && "font-semibold text-warn")}>
        {Number(value) === 0 ? "—" : formatMoney(value)}
      </dd>
    </div>
  );
}
