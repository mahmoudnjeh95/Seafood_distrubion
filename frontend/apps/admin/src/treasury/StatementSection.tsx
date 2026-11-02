import {
  type BankStatementLine,
  deleteStatementLine,
  importBankStatement,
  setStatementLineParty,
  useListCustomers,
  useListStatementLines,
  useListSuppliers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, Combobox, ConfirmButton, Table, Td, Th, toast } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { canCollect } from "../payments/shared";
import { compare } from "../purchasing/allocation";

type Problem = { row: number; message: string };

/** The bank's own statement of one bank account (P9-T09d, D-252): the Excel file the bank gives, imported line by
 * line, each line given to a customer (a debit) or a supplier (a credit). A copy of the bank's file: it changes no
 * balance of ours. */
export function StatementSection({
  accountId,
  dateFrom,
  dateTo,
}: {
  accountId: number;
  dateFrom: string;
  dateTo: string;
}) {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canWrite = canCollect(session);
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [busy, setBusy] = useState(false);
  const lines = useListStatementLines(accountId, {
    limit: 500,
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
  });
  const customers = useListCustomers({ status: "all" });
  const suppliers = useListSuppliers({ status: "all" });
  const rows = lines.data?.results ?? [];
  const refresh = () =>
    queryClient.invalidateQueries({ predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/treasury") });

  async function upload(file: File) {
    setBusy(true);
    setProblems([]);
    try {
      const report = await importBankStatement(accountId, { file });
      if (report.problems.length > 0) {
        setProblems(report.problems.map((error) => ({ row: error.row, message: error.message })));
        toast.error(t("admin.treasury.statement.refused"));
      } else {
        toast.success(t("admin.treasury.statement.imported", { created: report.created, skipped: report.skipped }));
        await refresh();
      }
    } catch (failure) {
      const found = fieldErrors(failure);
      toast.error(found.file ?? found.account ?? t("admin.treasury.statement.error"));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function setParty(line: BankStatementLine, value: string) {
    const id = value ? Number(value) : null;
    const forDebit = compare(line.debit, "0") > 0;
    try {
      await setStatementLineParty(
        line.id,
        forDebit ? { customer: id, supplier: null } : { customer: null, supplier: id },
      );
      await refresh();
    } catch (failure) {
      toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.treasury.statement.error"));
    }
  }

  async function remove(line: BankStatementLine) {
    try {
      await deleteStatementLine(line.id);
      await refresh();
    } catch {
      toast.error(t("admin.treasury.statement.error"));
    }
  }

  const optionsFor = (line: BankStatementLine) =>
    (compare(line.debit, "0") > 0 ? (customers.data ?? []) : (suppliers.data ?? [])).map((one) => ({
      value: String(one.id),
      label: `${one.name} · ${one.reference}`,
    }));

  return (
    <Card className="flex flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <CardTitle className="mb-0">{t("admin.treasury.statement.title")}</CardTitle>
        {canWrite && (
          <div className="ms-auto">
            <input
              ref={input}
              type="file"
              accept=".xlsx"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
              }}
            />
            <Button disabled={busy} onClick={() => input.current?.click()}>
              {t("admin.treasury.statement.upload")}
            </Button>
          </div>
        )}
      </div>
      <p className="text-[0.85rem] text-ink-2">{t("admin.treasury.statement.intro")}</p>

      {problems.length > 0 && (
        <ul role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.85rem] text-bad">
          {problems.slice(0, 20).map((problem) => (
            <li key={problem.row}>{t("admin.treasury.statement.rowError", problem)}</li>
          ))}
        </ul>
      )}

      {rows.length === 0 ? (
        <p className="text-ink-2">{t("admin.treasury.statement.empty")}</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.treasury.statement.columns.day")}</Th>
              <Th>{t("admin.treasury.statement.columns.label")}</Th>
              <Th numeric>{t("admin.treasury.statement.columns.debit")}</Th>
              <Th numeric>{t("admin.treasury.statement.columns.credit")}</Th>
              <Th numeric>{t("admin.treasury.statement.columns.balance")}</Th>
              <Th>{t("admin.treasury.statement.columns.party")}</Th>
              {canWrite && <Th>{null}</Th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((line) => {
              const chosen = line.customer ?? line.supplier;
              const hasMoney = compare(line.debit, "0") > 0 || compare(line.credit, "0") > 0;
              return (
                <tr key={line.id}>
                  <Td className="num whitespace-nowrap">{formatDate(line.day)}</Td>
                  <Td>{line.label}</Td>
                  <Td numeric className="num">
                    {compare(line.debit, "0") > 0 ? formatMoney(line.debit) : ""}
                  </Td>
                  <Td numeric className="num">
                    {compare(line.credit, "0") > 0 ? formatMoney(line.credit) : ""}
                  </Td>
                  <Td numeric className="num">
                    {line.balance !== null ? formatMoney(line.balance) : ""}
                  </Td>
                  <Td className="min-w-[14rem]">
                    {canWrite && hasMoney ? (
                      <Combobox
                        value={chosen ? String(chosen.id) : ""}
                        onValueChange={(value) => void setParty(line, value)}
                        options={optionsFor(line)}
                        empty={t("admin.treasury.statement.noParty")}
                        aria-label={t("admin.treasury.statement.columns.party")}
                      />
                    ) : (
                      (chosen?.name ?? "")
                    )}
                  </Td>
                  {canWrite && (
                    <Td className="text-end">
                      <ConfirmButton
                        variant="ghost"
                        title={t("admin.treasury.statement.removeTitle")}
                        rows={[[line.label, formatDate(line.day)]]}
                        onConfirm={() => void remove(line)}
                      >
                        {t("admin.treasury.statement.remove")}
                      </ConfirmButton>
                    </Td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
    </Card>
  );
}
