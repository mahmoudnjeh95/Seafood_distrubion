import type { SupplierInvoice } from "@frutti/api";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { cn, MoneyInput, Pill, Table, Td, Th } from "@frutti/ui";

import { type AllocationProblem, allocationProblem, type Allocations } from "./allocation";

/** One row per open invoice of the supplier, with the part of the payment that goes on it. */
export function AllocationTable({
  idPrefix,
  invoices,
  values,
  errors,
  onChange,
}: {
  idPrefix: string;
  invoices: readonly SupplierInvoice[];
  values: Allocations;
  errors: Record<number, string>;
  onChange: (invoiceId: number, value: string) => void;
}) {
  const { t } = useTranslation();
  const describe = (problem: AllocationProblem, invoice: SupplierInvoice) =>
    problem === "tooMuch"
      ? t("admin.supplierPayments.form.tooMuch", { amount: formatMoney(invoice.outstanding) })
      : t(`admin.supplierPayments.form.${problem}`);
  return (
    <Table>
      <thead>
        <tr>
          <Th>{t("admin.supplierPayments.form.invoice")}</Th>
          <Th className="max-[720px]:hidden">{t("admin.supplierPayments.form.invoiceDate")}</Th>
          <Th className="max-[720px]:hidden">{t("admin.supplierPayments.form.due")}</Th>
          <Th numeric>{t("admin.supplierPayments.form.outstanding")}</Th>
          <Th numeric>{t("admin.supplierPayments.form.allocation")}</Th>
        </tr>
      </thead>
      <tbody>
        {invoices.map((invoice) => {
          const inputId = `${idPrefix}-allocation-${invoice.id}`;
          const problem = allocationProblem(values[invoice.id] ?? "", invoice);
          // A problem the browser sees at once comes first; otherwise the server's answer for this line.
          const error = problem ? describe(problem, invoice) : errors[invoice.id];
          return (
            <tr key={invoice.id}>
              <Td className="num whitespace-nowrap">
                <span className="font-semibold">{invoice.number}</span>
                {invoice.supplier_reference && (
                  <div className="text-[0.8rem] text-ink-2">{invoice.supplier_reference}</div>
                )}
                {/* On a phone the due date goes under the number: the table keeps its amounts in view. */}
                <div className={cn("text-[0.8rem] min-[721px]:hidden", invoice.is_overdue ? "text-bad" : "text-ink-2")}>
                  {t("admin.supplierPayments.form.due")} {formatDate(invoice.due_date)}
                </div>
              </Td>
              <Td className="num whitespace-nowrap max-[720px]:hidden">{formatDate(invoice.invoice_date)}</Td>
              <Td className="num whitespace-nowrap max-[720px]:hidden">
                <span className={cn(invoice.is_overdue && "font-semibold text-bad")}>
                  {formatDate(invoice.due_date)}
                </span>
                {invoice.is_overdue && (
                  <Pill className="ms-2" tone="bad">
                    {t("admin.supplierInvoices.overdue")}
                  </Pill>
                )}
              </Td>
              <Td numeric className="whitespace-nowrap">
                {formatMoney(invoice.outstanding)}
              </Td>
              <Td numeric className="w-40">
                <MoneyInput
                  id={inputId}
                  inputMode="decimal"
                  aria-label={t("admin.supplierPayments.form.allocationFor", { number: invoice.number })}
                  value={values[invoice.id] ?? ""}
                  onChange={(event) => onChange(invoice.id, event.target.value)}
                  aria-invalid={error ? true : undefined}
                  autoComplete="off"
                  className="num text-end"
                />
                {error && <p className="mt-1 text-start text-[0.78rem] font-semibold text-bad">{error}</p>}
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}
