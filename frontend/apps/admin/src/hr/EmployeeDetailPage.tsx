import {
  ApiError,
  archiveEmployee,
  createLotWorkDay,
  deleteLotWorkDay,
  type Employee,
  restoreEmployee,
  useGetEmployee,
  useListBatches,
  useListLotWorkDays,
  useListSalaryPayments,
  useListSalaryRecords,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  cn,
  Dialog,
  EmptyState,
  Field,
  Icon,
  Input,
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
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useId, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { sum } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { todayInTunis } from "../receipts/shared";
import { EmployeeDialog } from "./EmployeeDialog";
import { PayRestricted } from "./Restricted";
import { canReadPay, canWritePay, DAY_FRACTIONS, monthLabel, refreshHr, STATUS_TONE } from "./shared";

function Detail({ label, children, numeric = false }: { label: string; children: ReactNode; numeric?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("break-words", numeric && "num")}>{children}</dd>
    </div>
  );
}

const NO_LOT = "none";

/** "Jours sur lot": days this employee worked on a lot cost days × monthly salary / 26 (D-041). */
function WorkDays({ employee, canEdit }: { employee: Employee; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const days = useListLotWorkDays({ employee: employee.id });
  const batches = useListBatches({ limit: 100 });
  const [workDate, setWorkDate] = useState(todayInTunis);
  const [fraction, setFraction] = useState<string>("1");
  const [batch, setBatch] = useState(NO_LOT);
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const add = useMutation({
    mutationFn: () =>
      createLotWorkDay({
        employee: employee.id,
        work_date: workDate,
        days: fraction,
        batch: batch === NO_LOT ? null : Number(batch),
        notes: notes.trim(),
      }),
    onSuccess: async () => {
      toast.success(t("admin.hr.workDays.added"));
      setNotes("");
      setErrors({});
      await refreshHr(queryClient);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.hr.workDays.error") });
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteLotWorkDay(id),
    onSuccess: async () => {
      toast.success(t("admin.hr.workDays.removed"));
      await refreshHr(queryClient);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!workDate) {
      setErrors({ work_date: t("admin.hr.form.required") });
      return;
    }
    setErrors({});
    add.mutate();
  }

  const list = days.data ?? [];
  return (
    <Card className="col-span-full">
      <CardTitle>{t("admin.hr.workDays.title")}</CardTitle>
      <p className="mb-3 text-[0.85rem] text-ink-2">{t("admin.hr.workDays.hint")}</p>
      {canEdit && (
        <form
          onSubmit={submit}
          noValidate
          aria-label={t("admin.hr.workDays.title")}
          className="mb-4 grid grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] items-start gap-3"
        >
          <Field label={t("admin.hr.workDays.date")} htmlFor={`${formId}-date`} error={errors.work_date}>
            <Input
              id={`${formId}-date`}
              type="date"
              max={todayInTunis()}
              value={workDate}
              onChange={(event) => setWorkDate(event.target.value)}
            />
          </Field>
          <Field label={t("admin.hr.workDays.days")} htmlFor={`${formId}-days`} error={errors.days}>
            <Select value={fraction} onValueChange={setFraction}>
              <SelectTrigger id={`${formId}-days`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DAY_FRACTIONS.map(({ value, label }) => (
                  <SelectItem key={value} value={value}>
                    {t(`admin.hr.workDays.fractions.${label}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("admin.hr.workDays.lot")} htmlFor={`${formId}-lot`} error={errors.batch}>
            <Select value={batch} onValueChange={setBatch}>
              <SelectTrigger id={`${formId}-lot`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_LOT}>{t("admin.hr.workDays.noLot")}</SelectItem>
                {(batches.data?.results ?? [])
                  .filter((one) => one.product.is_active || String(one.id) === batch)
                  .map((one) => (
                    <SelectItem key={one.id} value={String(one.id)}>
                      {`${one.number} · ${one.product.name}`}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("admin.hr.workDays.notes")} htmlFor={`${formId}-notes`} error={errors.notes}>
            <Input
              id={`${formId}-notes`}
              value={notes}
              maxLength={200}
              onChange={(event) => setNotes(event.target.value)}
            />
          </Field>
          <div className="flex items-end self-end">
            <Button type="submit" variant="primary" disabled={add.isPending}>
              <Icon name="plus" />
              {t("admin.hr.workDays.add")}
            </Button>
          </div>
          {errors.detail && (
            <p role="alert" className="col-span-full text-[0.88rem] font-semibold text-bad">
              {errors.detail}
            </p>
          )}
        </form>
      )}
      {days.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : list.length === 0 ? (
        <p className="text-ink-2">{t("admin.hr.workDays.empty")}</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.hr.workDays.date")}</Th>
              <Th>{t("admin.hr.workDays.lot")}</Th>
              <Th className="text-end">{t("admin.hr.workDays.days")}</Th>
              <Th className="text-end">{t("admin.hr.workDays.cost")}</Th>
              {canEdit && <Th />}
            </tr>
          </thead>
          <tbody>
            {list.map((day) => (
              <tr key={day.id}>
                <Td className="whitespace-nowrap">{formatDate(day.work_date)}</Td>
                <Td>
                  {day.batch ? (
                    <Link to={`/stock/lots/${day.batch.id}`} className="font-semibold hover:underline">
                      {day.batch.number}
                    </Link>
                  ) : (
                    <span className="text-ink-2">{t("admin.hr.workDays.noLot")}</span>
                  )}
                  {day.notes && <div className="text-[0.8rem] text-ink-2">{day.notes}</div>}
                </Td>
                <Td className="num whitespace-nowrap text-end">{day.days.replace(".", ",")}</Td>
                <Td className="num whitespace-nowrap text-end">{formatMoney(day.cost)}</Td>
                {canEdit && (
                  <Td className="text-end">
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={t("admin.hr.workDays.remove")}
                      title={t("admin.hr.workDays.remove")}
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(day.id)}
                    >
                      <Icon name="trash" />
                    </Button>
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <Td colSpan={2} className="font-semibold">
                {t("admin.hr.workDays.total")}
              </Td>
              <Td className="num text-end font-semibold">
                {sum(list.map((day) => day.days))
                  .replace(/\.?0+$/, "")
                  .replace(".", ",")}
              </Td>
              <Td className="num text-end font-semibold">{formatMoney(sum(list.map((day) => day.cost)))}</Td>
              {canEdit && <Td />}
            </tr>
          </tfoot>
        </Table>
      )}
    </Card>
  );
}

export function EmployeeDetailPage() {
  const session = useOutletContext<Session>();
  if (!canReadPay(session)) return <PayRestricted />;
  return <EmployeeDetail canEdit={canWritePay(session)} />;
}

function EmployeeDetail({ canEdit }: { canEdit: boolean }) {
  const { t, i18n } = useTranslation();
  const { employeeId } = useParams();
  const id = Number(employeeId);
  const validId = Number.isInteger(id) && id > 0;
  const employee = useGetEmployee(id, { query: { enabled: validId, retry: false } });
  const salaries = useListSalaryRecords({ employee: id }, { query: { enabled: validId } });
  const payments = useListSalaryPayments({ employee: id }, { query: { enabled: validId } });
  const [editing, setEditing] = useState(false);
  const queryClient = useQueryClient();

  const toggleActive = useMutation({
    mutationFn: (target: Employee) => (target.is_active ? archiveEmployee(target.id) : restoreEmployee(target.id)),
    onSuccess: async (saved) => {
      toast.success(t(saved.is_active ? "admin.hr.form.restoredDone" : "admin.hr.form.archivedDone"));
      await refreshHr(queryClient);
    },
  });

  const back = (
    <Link to="/salaires/employes" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.hr.detail.back")}
    </Link>
  );

  if (validId && employee.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!employee.data) {
    const missing = !validId || (employee.error instanceof ApiError && employee.error.status === 404);
    return (
      <>
        {back}
        <EmptyState
          illustration="shrimp"
          title={missing ? t("admin.hr.detail.notFound") : t("common.serverUnreachable")}
        />
      </>
    );
  }

  const data = employee.data;
  const empty = t("admin.hr.detail.empty");

  return (
    <>
      {back}
      <PageHeader eyebrow={data.reference} title={data.name}>
        {!data.is_active && <Pill tone="neutral">{t("admin.hr.employees.archived")}</Pill>}
        {canEdit && (
          <>
            <Button variant="ghost" disabled={toggleActive.isPending} onClick={() => toggleActive.mutate(data)}>
              {t(data.is_active ? "admin.hr.form.archive" : "admin.hr.form.restore")}
            </Button>
            <Button variant="primary" onClick={() => setEditing(true)}>
              {t("admin.hr.detail.edit")}
            </Button>
          </>
        )}
      </PageHeader>

      <div className="grid items-start gap-4 min-[960px]:grid-cols-[3fr_2fr]">
        <Card>
          <CardTitle>{t("admin.hr.detail.identity")}</CardTitle>
          <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-3">
            <Detail label={t("admin.hr.form.position")}>{data.position || empty}</Detail>
            <Detail label={t("admin.hr.form.phone")} numeric>
              {data.phone ? <a href={`tel:${data.phone.replace(/\s/g, "")}`}>{data.phone}</a> : empty}
            </Detail>
            <Detail label={t("admin.hr.form.hireDate")}>{data.hire_date ? formatDate(data.hire_date) : empty}</Detail>
            <Detail label={t("admin.hr.form.user")}>
              {data.user ? data.user.username : t("admin.hr.form.noUser")}
            </Detail>
            {data.notes && (
              <div className="col-span-full">
                <Detail label={t("admin.hr.form.notes")}>
                  <span className="whitespace-pre-line">{data.notes}</span>
                </Detail>
              </div>
            )}
          </dl>
        </Card>

        <Card>
          <CardTitle>{t("admin.hr.detail.pay")}</CardTitle>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
            <Detail label={t("admin.hr.form.salary")} numeric>
              {formatMoney(data.monthly_salary)}
            </Detail>
            <Detail label={t("admin.hr.form.cnssRate")} numeric>
              {`${data.cnss_rate.replace(".", ",")} %`}
            </Detail>
            <Detail label={t("admin.hr.form.employeeCnssRate")} numeric>
              {`${data.employee_cnss_rate.replace(".", ",")} %`}
            </Detail>
            <Detail label={t("admin.hr.form.cnssNumber")} numeric>
              {data.cnss_number || empty}
            </Detail>
            <Detail label={t("admin.hr.detail.unpaid")} numeric>
              {Number(data.unpaid) > 0 ? (
                <Pill tone="warn">{t("admin.hr.unpaidBadge", { amount: formatMoney(data.unpaid) })}</Pill>
              ) : (
                t("admin.hr.upToDate")
              )}
            </Detail>
          </dl>
        </Card>

        <Card className="col-span-full">
          <CardTitle>{t("admin.hr.detail.salaries")}</CardTitle>
          {salaries.isPending ? (
            <p className="text-ink-2">{t("common.loading")}</p>
          ) : (salaries.data ?? []).length === 0 ? (
            <p className="text-ink-2">{t("admin.hr.detail.noSalaries")}</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.hr.detail.month")}</Th>
                  <Th className="text-end">{t("admin.hr.payroll.columns.gross")}</Th>
                  <Th className="text-end">{t("admin.hr.payroll.columns.net")}</Th>
                  <Th className="text-end">{t("admin.hr.payroll.columns.paid")}</Th>
                  <Th className="text-end">{t("admin.hr.payroll.columns.outstanding")}</Th>
                  <Th>{t("admin.hr.payroll.columns.status")}</Th>
                </tr>
              </thead>
              <tbody>
                {(salaries.data ?? []).map((record) => (
                  <tr key={record.id}>
                    <Td className="capitalize">{monthLabel(record.month, i18n.language)}</Td>
                    <Td className="num whitespace-nowrap text-end">{formatMoney(record.gross)}</Td>
                    <Td className="num whitespace-nowrap text-end">{formatMoney(record.due_amount)}</Td>
                    <Td className="num whitespace-nowrap text-end">{formatMoney(record.paid_amount)}</Td>
                    <Td className="num whitespace-nowrap text-end">
                      {record.status === "approved" ? formatMoney(record.outstanding) : "—"}
                    </Td>
                    <Td>
                      <Pill tone={STATUS_TONE[record.status]}>{t(`admin.hr.status.${record.status}`)}</Pill>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card className="col-span-full">
          <CardTitle>{t("admin.hr.detail.payments")}</CardTitle>
          {payments.isPending ? (
            <p className="text-ink-2">{t("common.loading")}</p>
          ) : (payments.data ?? []).length === 0 ? (
            <p className="text-ink-2">{t("admin.hr.detail.noPayments")}</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.hr.detail.number")}</Th>
                  <Th>{t("admin.hr.pay.paidOn")}</Th>
                  <Th>{t("admin.hr.pay.method")}</Th>
                  <Th className="text-end">{t("admin.hr.pay.amount")}</Th>
                  <Th className="text-end">{t("admin.hr.detail.advance")}</Th>
                  <Th>{t("admin.hr.treasury.column")}</Th>
                </tr>
              </thead>
              <tbody>
                {(payments.data ?? []).map((payment) => (
                  <tr key={payment.id}>
                    <Td className="num whitespace-nowrap">
                      {payment.number}
                      {payment.kind === "advance" && (
                        <div className="text-[0.8rem] font-normal text-ink-2">{t("admin.hr.kind.advance")}</div>
                      )}
                    </Td>
                    <Td className="whitespace-nowrap">{formatDate(payment.paid_on)}</Td>
                    <Td>{t(`admin.hr.method.${payment.method}`)}</Td>
                    <Td className="num whitespace-nowrap text-end">{formatMoney(payment.amount)}</Td>
                    <Td className="num whitespace-nowrap text-end">
                      {Number(payment.unallocated) > 0 ? formatMoney(payment.unallocated) : "—"}
                    </Td>
                    <Td className="text-[0.85rem]">
                      {payment.treasury_debit
                        ? t("admin.hr.treasury.debited", {
                            amount: formatMoney(payment.treasury_debit.amount),
                            account: payment.treasury_debit.account,
                            date: formatDate(payment.treasury_debit.day),
                          })
                        : "—"}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <WorkDays employee={data} canEdit={canEdit && data.is_active} />
      </div>

      <Dialog open={editing} onOpenChange={setEditing}>
        {editing && <EmployeeDialog key={data.updated_at} employee={data} onDone={() => setEditing(false)} />}
      </Dialog>
    </>
  );
}
