import {
  createCustomerPayment,
  type CustomerPaymentMethodEnum,
  type CustomerPaymentWrite,
  useGetCustomerBalance,
  useListBanks,
  useListCustomers,
  useListInstruments,
  useListPartyDocuments,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  cn,
  Combobox,
  Field,
  Input,
  PageHeader,
  Pill,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useMemo, useState } from "react";
import { Link, Navigate, useNavigate, useOutletContext, useSearchParams } from "react-router";

import { subtract, sum } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { asTyped, compare, spread } from "../purchasing/allocation";
import { ConfirmPaymentDialog } from "./ConfirmPaymentDialog";
import {
  describeLine,
  errorsByLine,
  type LineProblem,
  lineProblems,
  linesPayload,
  linesTotal,
  newLine,
  type PaymentLine,
} from "./lines";
import { type OpenItem, openItems } from "./openItems";
import { countsOf, PartyDocumentCounts } from "./PartyDocumentCounts";
import { PaymentLinesEditor } from "./PaymentLinesEditor";
import { canCollect, CUSTOMER_PAYMENT_METHODS, refreshAfterPayment, todayInput } from "./shared";
import { TotalsBar } from "./TotalsBar";

type Line = PaymentLine<CustomerPaymentMethodEnum>;

/** "Nouveau règlement": money received from a customer, line by line (cash, cheques, traites, transfers, card),
 * spread over their open invoices and BLs; what is not allocated stays their credit (D-062, D-197). */
export function CustomerPaymentFormPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const formId = useId();
  const [params] = useSearchParams();
  const customers = useListCustomers({ status: "all" });
  const banks = useListBanks();
  const documents = useListPartyDocuments();
  const [customer, setCustomer] = useState(params.get("client") ?? "");
  const [receivedOn, setReceivedOn] = useState(todayInput);
  const [lines, setLines] = useState<Line[]>(() => [newLine<CustomerPaymentMethodEnum>("cash")]);
  const [allocations, setAllocations] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [checked, setChecked] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverLineErrors, setServerLineErrors] = useState<Record<number, Record<string, string>>>({});
  const [confirming, setConfirming] = useState<CustomerPaymentWrite | null>(null);

  const customerId = Number(customer) || 0;
  const balance = useGetCustomerBalance(customerId, { query: { enabled: customerId > 0 } });
  const effets = useListInstruments(
    { customer: customerId, direction: "received", status: "portfolio,deposited", limit: 200 },
    { query: { enabled: customerId > 0 } },
  );
  const items = useMemo(() => openItems(balance.data?.open_sales ?? []), [balance.data]);
  const chosen = (customers.data ?? []).find((one) => String(one.id) === customer);
  const bankRows = banks.data ?? [];

  const total = linesTotal(lines);
  const typed = items.map((item) => ({ item, value: parseDecimalInput((allocations[item.key] ?? "").trim(), 3) }));
  const itemProblem = (item: OpenItem): string | null => {
    const raw = (allocations[item.key] ?? "").trim();
    if (raw === "") return null;
    const value = parseDecimalInput(raw, 3);
    if (value === null || value.startsWith("-")) return t("admin.supplierPayments.form.money");
    if (compare(value, "0") === 0) return t("admin.supplierPayments.form.positive");
    if (compare(value, item.outstanding) > 0)
      return t("admin.supplierPayments.form.tooMuch", { amount: formatMoney(item.outstanding) });
    return null;
  };
  const allocated = sum(typed.flatMap(({ value }) => (value !== null && !value.startsWith("-") ? [value] : [])));
  const remaining = subtract(total, allocated);
  const overAllocated = remaining.startsWith("-");
  const inPortfolio = sum((effets.data?.results ?? []).map((row) => row.amount));
  const owed = balance.data?.balance ?? "0.000";
  const exposure = sum([owed, inPortfolio]);

  const problems = lineProblems(lines);
  const describe = (problem: LineProblem) => t(`admin.treasury.lines.problems.${problem}`);
  const lineErrors: Record<number, Record<string, string>> = {};
  lines.forEach((_line, index) => {
    const fromBrowser = checked
      ? Object.fromEntries(Object.entries(problems[index] ?? {}).map(([field, code]) => [field, describe(code)]))
      : {};
    lineErrors[index] = { ...(serverLineErrors[index] ?? {}), ...fromBrowser };
  });

  const save = useMutation({
    mutationFn: (payload: CustomerPaymentWrite) => createCustomerPayment(payload),
    onSuccess: async (saved) => {
      toast.success(t("admin.payments.dialog.done", { number: saved.number }));
      await refreshAfterPayment(queryClient);
      void navigate(`/clients/${customer}`);
    },
    onError: (failure) => {
      setConfirming(null);
      const fromServer = fieldErrors(failure);
      const { lines: byLine, rest } = errorsByLine(fromServer);
      setServerLineErrors(byLine);
      setErrors(Object.keys(fromServer).length > 0 ? rest : { detail: t("admin.payments.dialog.error") });
    },
  });

  if (!canCollect(session)) return <Navigate to="/reglements" replace />;

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!customer) found.customer = t("admin.supplierPayments.form.required");
    if (!receivedOn) found.received_on = t("admin.supplierPayments.form.required");
    const refused = items.some((item) => itemProblem(item) !== null);
    setErrors(found);
    setChecked(true);
    setServerLineErrors({});
    if (Object.keys(found).length > 0 || Object.keys(problems).length > 0 || refused || overAllocated) return;
    setConfirming({
      customer: customerId,
      received_on: receivedOn,
      amount: total,
      lines: linesPayload(lines, { withDrawer: true }),
      notes: notes.trim(),
      allocations: typed.flatMap(({ item, value }) =>
        value === null || compare(value, "0") <= 0
          ? []
          : [item.kind === "invoice" ? { invoice: item.id, amount: value } : { sale: item.id, amount: value }],
      ),
    });
  }

  const id = (name: string) => `${formId}-${name}`;

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.sales")} title={t("admin.treasury.form.customerTitle")} />

      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-[2fr_1fr] gap-4 max-[640px]:grid-cols-1">
          <Field label={t("admin.treasury.form.customer")} htmlFor={id("customer")} error={errors.customer}>
            <Combobox
              id={id("customer")}
              value={customer}
              onValueChange={(value) => {
                setCustomer(value);
                setAllocations({});
              }}
              options={(customers.data ?? [])
                .filter((one) => !one.is_walk_in && (one.is_active || String(one.id) === customer))
                .map((one) => {
                  const label = `${one.name} · ${one.reference}`;
                  return {
                    value: String(one.id),
                    label,
                    detail: (
                      <span className="flex items-center gap-3">
                        {label}
                        <PartyDocumentCounts counts={countsOf(documents.data?.customers, one.id)} side="customer" />
                      </span>
                    ),
                  };
                })}
              empty={t("admin.treasury.form.noCustomer")}
              aria-invalid={errors.customer ? true : undefined}
            />
          </Field>
          <Field label={t("admin.payments.dialog.receivedOn")} htmlFor={id("day")} error={errors.received_on}>
            <Input
              id={id("day")}
              type="date"
              max={todayInput()}
              value={receivedOn}
              onChange={(event) => setReceivedOn(event.target.value)}
            />
          </Field>
          {chosen && balance.data && (
            <dl className="col-span-full grid grid-cols-5 gap-3 rounded-control bg-surface-2 p-3 max-[900px]:grid-cols-2">
              <Figure label={t("admin.treasury.form.balance")} value={formatMoney(owed)} />
              <Figure
                label={t("admin.treasury.form.overdue")}
                value={formatMoney(balance.data.overdue)}
                bad={compare(balance.data.overdue, "0") > 0}
              />
              <Figure label={t("admin.treasury.form.inPortfolio")} value={formatMoney(inPortfolio)} />
              <Figure
                label={t("admin.treasury.form.exposure")}
                value={formatMoney(exposure)}
                bad={compare(balance.data.credit_limit, "0") > 0 && compare(exposure, balance.data.credit_limit) > 0}
              />
              <Figure
                label={t("admin.treasury.form.creditLimit")}
                value={
                  compare(balance.data.credit_limit, "0") > 0
                    ? formatMoney(balance.data.credit_limit)
                    : t("admin.treasury.form.noLimit")
                }
              />
            </dl>
          )}
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.treasury.lines.title")}</CardTitle>
          <PaymentLinesEditor
            idPrefix={formId}
            lines={lines}
            onChange={setLines}
            methods={CUSTOMER_PAYMENT_METHODS}
            methodLabel={(method) => t(`admin.sales.methods.${method}`)}
            banks={bankRows}
            errors={lineErrors}
            withDrawer
            drawerPlaceholder={chosen?.name ?? ""}
            issuedOn={receivedOn}
          />
          {(errors.amount ?? errors.lines) && (
            <p className="text-[0.78rem] font-semibold text-bad">{errors.amount ?? errors.lines}</p>
          )}
        </Card>

        <Card className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle className="mb-0">{t("admin.treasury.form.openItems")}</CardTitle>
            {items.length > 0 && (
              <div className="ms-auto flex gap-2">
                <Button variant="ghost" onClick={() => setAllocations({})}>
                  {t("admin.treasury.form.clear")}
                </Button>
                <Button
                  disabled={total === "0.000"}
                  onClick={() => {
                    const shares = spread(
                      total,
                      items.map((item) => item.outstanding),
                    );
                    setAllocations(
                      Object.fromEntries(items.map((item, index) => [item.key, asTyped(shares[index] ?? "")])),
                    );
                  }}
                >
                  {t("admin.treasury.form.auto")}
                </Button>
              </div>
            )}
          </div>
          <p className="text-[0.85rem] text-ink-2">{t("admin.treasury.form.openItemsHint")}</p>
          {!customer ? (
            <p className="text-ink-2">{t("admin.treasury.form.chooseCustomerFirst")}</p>
          ) : balance.isPending ? (
            <p className="text-ink-2">{t("common.loading")}</p>
          ) : items.length === 0 ? (
            <p className="text-ink-2">{t("admin.treasury.form.nothingOpen")}</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.treasury.form.document")}</Th>
                  <Th className="max-[720px]:hidden">{t("admin.treasury.form.day")}</Th>
                  <Th>{t("admin.treasury.form.due")}</Th>
                  <Th numeric>{t("admin.treasury.form.outstanding")}</Th>
                  <Th numeric>{t("admin.supplierPayments.form.allocation")}</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const problem = itemProblem(item);
                  return (
                    <tr key={item.key}>
                      <Td className="num whitespace-nowrap">
                        <span className="font-semibold">{item.number}</span>
                        {item.kind === "invoice" && (
                          <div className="text-[0.8rem] text-ink-2">{item.sales.join(", ")}</div>
                        )}
                      </Td>
                      <Td className="num whitespace-nowrap max-[720px]:hidden">{formatDate(item.day)}</Td>
                      <Td className="num whitespace-nowrap">
                        <span className={cn(item.isOverdue && "font-semibold text-bad")}>{formatDate(item.dueOn)}</span>
                        {item.isOverdue && (
                          <Pill className="ms-2" tone="bad">
                            {t("admin.treasury.form.late", { count: item.ageDays })}
                          </Pill>
                        )}
                      </Td>
                      <Td numeric className="whitespace-nowrap">
                        {formatMoney(item.outstanding)}
                      </Td>
                      <Td numeric className="w-40">
                        <div className="flex items-center gap-1">
                          <Input
                            id={id(`allocation-${item.key}`)}
                            inputMode="decimal"
                            aria-label={t("admin.supplierPayments.form.allocationFor", { number: item.number })}
                            value={allocations[item.key] ?? ""}
                            onChange={(event) =>
                              setAllocations((current) => ({ ...current, [item.key]: event.target.value }))
                            }
                            aria-invalid={problem ? true : undefined}
                            autoComplete="off"
                            className="num text-end"
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={t("admin.treasury.form.payAll", { number: item.number })}
                            onClick={() =>
                              setAllocations((current) => ({ ...current, [item.key]: asTyped(item.outstanding) }))
                            }
                          >
                            =
                          </Button>
                        </div>
                        {problem && <p className="mt-1 text-start text-[0.78rem] font-semibold text-bad">{problem}</p>}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
          {overAllocated && (
            <p className="text-[0.78rem] font-semibold text-bad">{t("admin.supplierPayments.form.overAllocated")}</p>
          )}
          {errors.allocations && <p className="text-[0.78rem] font-semibold text-bad">{errors.allocations}</p>}
        </Card>

        <Card>
          <Field label={t("admin.supplierPayments.form.notes")} htmlFor={id("notes")} error={errors.notes}>
            <textarea
              id={id("notes")}
              rows={2}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
            />
          </Field>
        </Card>

        {errors.detail && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail}
          </p>
        )}

        <TotalsBar
          total={total}
          allocated={allocated}
          remaining={remaining}
          overAllocated={overAllocated}
          labels={{
            total: t("admin.treasury.form.receivedTotal"),
            allocated: t("admin.supplierPayments.form.allocatedTotal"),
            remaining: t("admin.treasury.form.credit"),
          }}
        >
          <Button asChild>
            <Link to={customer ? `/clients/${customer}` : "/reglements"}>{t("admin.payments.dialog.cancel")}</Link>
          </Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {t("admin.payments.dialog.confirm")}
          </Button>
        </TotalsBar>
      </form>

      <ConfirmPaymentDialog
        open={confirming !== null}
        title={t("admin.treasury.form.confirmCustomer", { name: chosen?.name ?? "" })}
        rows={[
          [t("admin.treasury.form.receivedTotal"), formatMoney(total)],
          [t("admin.supplierPayments.form.allocatedTotal"), formatMoney(allocated)],
          [t("admin.treasury.form.credit"), formatMoney(remaining)],
        ]}
        means={lines.map((line) =>
          describeLine(line, {
            methodLabel: (method) => t(`admin.sales.methods.${method}`),
            banks: bankRows,
            formatDate,
          }),
        )}
        pending={save.isPending}
        onCancel={() => setConfirming(null)}
        onConfirm={() => confirming && save.mutate(confirming)}
      />
    </>
  );
}

function Figure({ label, value, bad = false }: { label: string; value: string; bad?: boolean }) {
  return (
    <div>
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("num font-bold", bad && "text-bad")}>{value}</dd>
    </div>
  );
}
