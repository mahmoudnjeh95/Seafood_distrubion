import {
  approveSalaryMonth,
  approveSalaryRecord,
  deleteSalaryRecord,
  generateSalaryMonth,
  type SalaryRecord,
  useGetPayrollSummary,
  useListSalaryRecords,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Dialog, EmptyState, Icon, PageHeader, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { HrTabs } from "./HrTabs";
import { PayRestricted } from "./Restricted";
import { AdjustmentDialog, SalaryPaymentDialog, SalaryRecordDialog } from "./SalaryDialogs";
import { canReadPay, canWritePay, currentMonth, monthLabel, refreshHr, shiftMonth, STATUS_TONE } from "./shared";

type Dialogs = { kind: "edit" | "pay" | "adjust" | "prime"; record: SalaryRecord } | null;

export function PayrollPage() {
  const session = useOutletContext<Session>();
  if (!canReadPay(session)) return <PayRestricted />;
  return <Payroll canEdit={canWritePay(session)} />;
}

function Payroll({ canEdit }: { canEdit: boolean }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [month, setMonth] = useState(currentMonth);
  const [dialog, setDialog] = useState<Dialogs>(null);

  const summary = useGetPayrollSummary({ month });
  const records = useListSalaryRecords({ month });
  const list = records.data ?? [];
  const drafts = list.filter((record) => record.status === "draft");

  const generate = useMutation({
    mutationFn: () => generateSalaryMonth({ month }),
    onSuccess: async (result) => {
      toast.success(
        result.created > 0
          ? t("admin.hr.payroll.generated", { count: result.created })
          : t("admin.hr.payroll.nothingToGenerate"),
      );
      await refreshHr(queryClient);
    },
    onError: (failure) => toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.hr.payroll.error")),
  });
  const approveAll = useMutation({
    mutationFn: () => approveSalaryMonth({ month }),
    onSuccess: async (result) => {
      toast.success(t("admin.hr.payroll.approvedCount", { count: result.approved }));
      await refreshHr(queryClient);
    },
    onError: () => toast.error(t("admin.hr.payroll.error")),
  });
  const approveOne = useMutation({
    mutationFn: (record: SalaryRecord) => approveSalaryRecord(record.id),
    onSuccess: async () => {
      toast.success(t("admin.hr.payroll.approvedOne"));
      await refreshHr(queryClient);
    },
    onError: () => toast.error(t("admin.hr.payroll.error")),
  });
  const remove = useMutation({
    mutationFn: (record: SalaryRecord) => deleteSalaryRecord(record.id),
    onSuccess: async () => {
      toast.success(t("admin.hr.payroll.deleted"));
      await refreshHr(queryClient);
    },
    onError: () => toast.error(t("admin.hr.payroll.error")),
  });

  const totals = summary.data;
  const busy = generate.isPending || approveAll.isPending || approveOne.isPending || remove.isPending;

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.finance")} title={t("admin.hr.payroll.title")}>
        {canEdit && (
          <>
            <Button onClick={() => generate.mutate()} disabled={busy}>
              <Icon name="plus" />
              {t("admin.hr.payroll.generate")}
            </Button>
            <Button variant="primary" onClick={() => approveAll.mutate()} disabled={busy || drafts.length === 0}>
              <Icon name="check" />
              {t("admin.hr.payroll.approveAll")}
            </Button>
          </>
        )}
      </PageHeader>

      <HrTabs />
      {!canEdit && <p className="text-ink-2">{t("admin.hr.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Button
          size="icon"
          variant="ghost"
          aria-label={t("admin.hr.payroll.previous")}
          title={t("admin.hr.payroll.previous")}
          onClick={() => setMonth((current) => shiftMonth(current, -1))}
        >
          ‹
        </Button>
        <h2 className="min-w-40 text-center text-[1.05rem] font-bold capitalize" aria-live="polite">
          {monthLabel(month, i18n.language)}
        </h2>
        <Button
          size="icon"
          variant="ghost"
          aria-label={t("admin.hr.payroll.next")}
          title={t("admin.hr.payroll.next")}
          disabled={month >= currentMonth()}
          onClick={() => setMonth((current) => shiftMonth(current, 1))}
        >
          ›
        </Button>
        {totals && totals.unpaid_records > 0 && (
          <Pill tone="warn" className="ms-auto">
            {t("admin.hr.payroll.unpaidAll", {
              amount: formatMoney(totals.unpaid_total),
              count: totals.unpaid_records,
            })}
          </Pill>
        )}
      </Card>

      {totals && totals.records > 0 && (
        <Card>
          <CardTitle>{t("admin.hr.payroll.summary")}</CardTitle>
          <dl className="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-4">
            {(
              [
                ["gross", totals.gross],
                ["employerCnss", totals.employer_cnss],
                ["employeeCnss", totals.employee_cnss],
                ["net", totals.net],
                ["expense", totals.expense],
                ["paid", totals.paid],
                ["outstanding", totals.outstanding],
              ] as const
            ).map(([key, amount]) => (
              <div key={key}>
                <dt className="text-[0.78rem] font-semibold text-ink-2">{t(`admin.hr.payroll.totals.${key}`)}</dt>
                <dd className="num text-[1.05rem] font-bold">{formatMoney(amount)}</dd>
              </div>
            ))}
          </dl>
          {totals.drafts > 0 && (
            <p className="mt-3 text-[0.85rem] text-ink-2">
              {t("admin.hr.payroll.draftsNote", { count: totals.drafts })}
            </p>
          )}
        </Card>
      )}

      {records.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : records.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        <EmptyState illustration="mix" title={t("admin.hr.payroll.empty")}>
          {canEdit ? t("admin.hr.payroll.emptyBody") : t("admin.hr.payroll.emptyBodyReadOnly")}
        </EmptyState>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.hr.payroll.columns.employee")}</Th>
                <Th className="text-end max-[900px]:hidden">{t("admin.hr.payroll.columns.gross")}</Th>
                <Th className="text-end max-[900px]:hidden">{t("admin.hr.payroll.columns.employerCnss")}</Th>
                <Th className="text-end max-[900px]:hidden">{t("admin.hr.payroll.columns.employeeCnss")}</Th>
                <Th className="text-end">{t("admin.hr.payroll.columns.net")}</Th>
                <Th className="text-end">{t("admin.hr.payroll.columns.paid")}</Th>
                <Th className="text-end">{t("admin.hr.payroll.columns.outstanding")}</Th>
                <Th>{t("admin.hr.payroll.columns.status")}</Th>
                {canEdit && <Th />}
              </tr>
            </thead>
            <tbody>
              {list.map((record) => (
                <tr key={record.id}>
                  <Td>
                    <Link
                      to={`/salaires/employes/${record.employee.id}`}
                      className="font-semibold text-ink hover:underline"
                    >
                      {record.employee.name}
                    </Link>
                    {record.employee.position && (
                      <div className="text-[0.8rem] text-ink-2">{record.employee.position}</div>
                    )}
                    {record.adjustments.map((adjustment) => (
                      <div key={adjustment.id} className="text-[0.8rem] text-ink-2">
                        {t(`admin.hr.adjustKind.${adjustment.kind}`)}
                        {` ${formatMoney(adjustment.amount)} · ${adjustment.reason}`}
                      </div>
                    ))}
                  </Td>
                  <Td className="num whitespace-nowrap text-end max-[900px]:hidden">{formatMoney(record.gross)}</Td>
                  <Td className="num whitespace-nowrap text-end max-[900px]:hidden">
                    {formatMoney(record.employer_cnss)}
                  </Td>
                  <Td className="num whitespace-nowrap text-end max-[900px]:hidden">
                    {formatMoney(record.employee_cnss)}
                  </Td>
                  <Td className="num whitespace-nowrap text-end font-semibold">{formatMoney(record.due_amount)}</Td>
                  <Td className="num whitespace-nowrap text-end">
                    {formatMoney(record.paid_amount)}
                    {record.payments.map(
                      (line) =>
                        line.treasury_debit && (
                          <div key={line.id} className="text-[0.8rem] font-normal text-ink-2">
                            {t("admin.hr.treasury.debited", {
                              amount: formatMoney(line.treasury_debit.amount),
                              account: line.treasury_debit.account,
                              date: formatDate(line.treasury_debit.day),
                            })}
                          </div>
                        ),
                    )}
                  </Td>
                  <Td className="num whitespace-nowrap text-end">
                    {record.status === "approved" && Number(record.outstanding) > 0 ? (
                      <Pill tone="warn">{t("admin.hr.unpaidBadge", { amount: formatMoney(record.outstanding) })}</Pill>
                    ) : record.status === "approved" ? (
                      <Pill tone="good">{t("admin.hr.payroll.paidInFull")}</Pill>
                    ) : (
                      <span className="text-ink-2">—</span>
                    )}
                  </Td>
                  <Td>
                    <Pill tone={STATUS_TONE[record.status]}>{t(`admin.hr.status.${record.status}`)}</Pill>
                  </Td>
                  {canEdit && (
                    <Td className="whitespace-nowrap text-end">
                      {record.status === "draft" ? (
                        <span className="inline-flex gap-1">
                          <Button onClick={() => setDialog({ kind: "edit", record })}>
                            {t("admin.hr.payroll.edit")}
                          </Button>
                          <Button variant="primary" disabled={busy} onClick={() => approveOne.mutate(record)}>
                            {t("admin.hr.payroll.approve")}
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            disabled={busy}
                            aria-label={t("admin.hr.payroll.delete")}
                            title={t("admin.hr.payroll.delete")}
                            onClick={() => remove.mutate(record)}
                          >
                            <Icon name="trash" />
                          </Button>
                        </span>
                      ) : (
                        <span className="inline-flex gap-1">
                          <Button
                            variant="primary"
                            disabled={Number(record.outstanding) <= 0}
                            onClick={() => setDialog({ kind: "pay", record })}
                          >
                            {t("admin.hr.payroll.pay")}
                          </Button>
                          <Button onClick={() => setDialog({ kind: "adjust", record })}>
                            {t("admin.hr.payroll.adjust")}
                          </Button>
                          <Button onClick={() => setDialog({ kind: "prime", record })}>
                            {t("admin.hr.payroll.prime")}
                          </Button>
                        </span>
                      )}
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <Dialog open={dialog !== null} onOpenChange={(open) => !open && setDialog(null)}>
        {dialog?.kind === "edit" && <SalaryRecordDialog record={dialog.record} onDone={() => setDialog(null)} />}
        {dialog?.kind === "pay" && <SalaryPaymentDialog record={dialog.record} onDone={() => setDialog(null)} />}
        {dialog?.kind === "adjust" && <AdjustmentDialog record={dialog.record} onDone={() => setDialog(null)} />}
        {dialog?.kind === "prime" && <AdjustmentDialog prime record={dialog.record} onDone={() => setDialog(null)} />}
      </Dialog>
    </>
  );
}
