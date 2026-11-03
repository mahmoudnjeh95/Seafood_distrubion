import { useListEmployees } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  Dialog,
  EmptyState,
  Icon,
  Input,
  PageHeader,
  Pager,
  Pill,
  SortTh,
  Table,
  Td,
  TotalsRow,
  useTableView,
  useUrlState,
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { type Status, StatusFilter } from "../lib/StatusFilter";
import { totalOf } from "../lib/totals";
import { useDebounced } from "../lib/useDebounced";
import { EmployeeDialog } from "./EmployeeDialog";
import { HrTabs } from "./HrTabs";
import { PayRestricted } from "./Restricted";
import { canReadPay, canWritePay } from "./shared";

export function EmployeesPage() {
  const session = useOutletContext<Session>();
  if (!canReadPay(session)) return <PayRestricted />;
  return <Employees canEdit={canWritePay(session)} />;
}

function Employees({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [search, setSearch] = useUrlState("q");
  const [status, setStatus] = useState<Status>("active");
  const [creating, setCreating] = useState(false);
  const query = useDebounced(search.trim());

  const employees = useListEmployees(
    { status, ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData } },
  );
  const list = employees.data ?? [];
  const filtering = query !== "" || status !== "active";

  const view = useTableView(list, {
    reference: (employee) => employee.reference,
    name: (employee) => employee.name,
    phone: (employee) => employee.phone,
    salary: (employee) => Number(employee.monthly_salary),
    unpaid: (employee) => Number(employee.unpaid),
  });
  const sorting = { sort: view.sort, onSort: view.toggleSort };

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.finance")} title={t("admin.hr.employees.title")}>
        {canEdit && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Icon name="plus" />
            {t("admin.hr.employees.add")}
          </Button>
        )}
      </PageHeader>

      <HrTabs />
      {!canEdit && <p className="text-ink-2">{t("admin.hr.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.hr.employees.search")}
          placeholder={t("admin.hr.employees.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <StatusFilter
          value={status}
          onChange={setStatus}
          label={t("admin.hr.employees.show")}
          labels={{
            active: t("admin.hr.employees.status.active"),
            archived: t("admin.hr.employees.status.archived"),
            all: t("admin.hr.employees.status.all"),
          }}
        />
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {employees.data && t("admin.hr.employees.count", { count: list.length })}
        </span>
      </Card>

      {employees.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : employees.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.hr.employees.noMatch")}</p>
        ) : (
          <EmptyState illustration="mix" title={t("admin.hr.employees.empty")}>
            {t("admin.hr.employees.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="reference" {...sorting}>
                  {t("admin.hr.employees.columns.reference")}
                </SortTh>
                <SortTh sortKey="name" {...sorting}>
                  {t("admin.hr.employees.columns.name")}
                </SortTh>
                <SortTh sortKey="phone" {...sorting} className="max-[720px]:hidden">
                  {t("admin.hr.employees.columns.phone")}
                </SortTh>
                <SortTh numeric sortKey="salary" {...sorting}>
                  {t("admin.hr.employees.columns.salary")}
                </SortTh>
                <SortTh numeric sortKey="unpaid" {...sorting}>
                  {t("admin.hr.employees.columns.unpaid")}
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((employee) => (
                <tr
                  key={employee.id}
                  onClick={() => void navigate(`/salaires/employes/${employee.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap text-ink-2">{employee.reference}</Td>
                  <Td>
                    <Link
                      to={`/salaires/employes/${employee.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {employee.name}
                    </Link>
                    {!employee.is_active && (
                      <Pill className="ms-2" tone="neutral">
                        {t("admin.hr.employees.archived")}
                      </Pill>
                    )}
                    {employee.position && <div className="text-[0.8rem] text-ink-2">{employee.position}</div>}
                  </Td>
                  <Td className="num whitespace-nowrap max-[720px]:hidden">{employee.phone}</Td>
                  <Td className="num whitespace-nowrap text-end">{formatMoney(employee.monthly_salary)}</Td>
                  <Td className="num whitespace-nowrap text-end">
                    {Number(employee.unpaid) > 0 ? (
                      <Pill tone="warn">{t("admin.hr.unpaidBadge", { amount: formatMoney(employee.unpaid) })}</Pill>
                    ) : (
                      <span className="text-ink-2">{t("admin.hr.upToDate")}</span>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
            <TotalsRow
              span={3}
              cells={[
                { value: totalOf(view.rows, (e) => e.monthly_salary) },
                { value: totalOf(view.rows, (e) => e.unpaid) },
              ]}
            />
          </Table>
          <Pager {...view.pager} />
        </Card>
      )}

      <Dialog open={creating} onOpenChange={setCreating}>
        {creating && (
          <EmployeeDialog
            onDone={(created) => {
              setCreating(false);
              if (created) void navigate(`/salaires/employes/${created.id}`);
            }}
          />
        )}
      </Dialog>
    </>
  );
}
