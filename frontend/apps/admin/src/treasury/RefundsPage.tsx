import {
  type CustomerRefund,
  type ListCustomerRefundsStatus,
  payCustomerRefund,
  type RefundMethodEnum,
  useListCustomerRefunds,
  useListTreasuryAccounts,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
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
  useUrlState,
} from "@frutti/ui";
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { asTyped } from "../lib/lines";
import { useDebounced } from "../lib/useDebounced";
import { TresorerieRibbon } from "./TresorerieRibbon";

const FILTERS = ["open", "to_refund", "partial", "refunded", "all"] as const;
const METHODS = ["cash", "transfer", "cheque"] as const;
const DEFAULT_ACCOUNT = "default";
const TONES = { to_refund: "warn", partial: "sea", refunded: "good" } as const;

/** Pay back all or part of what is left on a refund: the money leaves the chosen caisse or bank account. */
function PayDialog({ refund, onClose }: { refund: CustomerRefund; onClose: () => void }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const [amount, setAmount] = useState(asTyped(refund.left));
  const [method, setMethod] = useState<RefundMethodEnum>("cash");
  const [account, setAccount] = useState(DEFAULT_ACCOUNT);
  const [paidOn, setPaidOn] = useState("");
  const [reference, setReference] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const accounts = useListTreasuryAccounts({ active_only: true });
  const choices = (accounts.data ?? []).filter((row) =>
    method === "cash" ? row.kind === "cash" || row.kind === "driver" : row.kind === "bank",
  );

  const pay = useMutation({
    mutationFn: () => {
      const value = parseDecimalInput(amount.trim(), 3);
      if (value === null) {
        setErrors({ amount: t("admin.refunds.amountError") });
        return Promise.reject(new Error("invalid"));
      }
      return payCustomerRefund(refund.id, {
        amount: value,
        method,
        account: account === DEFAULT_ACCOUNT ? null : Number(account),
        paid_on: paidOn || null,
        reference: reference.trim(),
      });
    },
    onSuccess: async (saved) => {
      toast.success(t("admin.refunds.paid", { number: saved.number, amount: formatMoney(saved.refunded) }));
      await queryClient.invalidateQueries();
      onClose();
    },
    onError: (failure) => {
      const found = fieldErrors(failure);
      if (Object.keys(found).length > 0) setErrors(found);
      else if (!(failure instanceof Error && failure.message === "invalid")) toast.error(t("admin.refunds.error"));
    },
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{t("admin.refunds.payTitle", { number: refund.number })}</DialogTitle>
        <DialogDescription>
          {t("admin.refunds.payBody", { customer: refund.customer.name, left: formatMoney(refund.left) })}
        </DialogDescription>
        <div className="grid grid-cols-2 gap-3 max-[560px]:grid-cols-1">
          <Field label={t("admin.refunds.amount")} htmlFor={`${formId}-amount`} error={errors.amount}>
            <MoneyInput
              id={`${formId}-amount`}
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </Field>
          <Field label={t("admin.refunds.paidOn")} htmlFor={`${formId}-day`} error={errors.paid_on}>
            <Input
              id={`${formId}-day`}
              type="date"
              value={paidOn}
              onChange={(event) => setPaidOn(event.target.value)}
            />
          </Field>
          <Field label={t("admin.refunds.method")} htmlFor={`${formId}-method`} error={errors.method}>
            <Select
              value={method}
              onValueChange={(value) => {
                setMethod(value as RefundMethodEnum);
                setAccount(DEFAULT_ACCOUNT);
              }}
            >
              <SelectTrigger id={`${formId}-method`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {METHODS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {t(`admin.refunds.methods.${value}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("admin.refunds.account")} htmlFor={`${formId}-account`} error={errors.account}>
            <Select value={account} onValueChange={setAccount}>
              <SelectTrigger id={`${formId}-account`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DEFAULT_ACCOUNT}>
                  {t(method === "cash" ? "admin.refunds.defaultCash" : "admin.refunds.defaultBank")}
                </SelectItem>
                {choices.map((row) => (
                  <SelectItem key={row.id} value={String(row.id)}>
                    {row.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("admin.refunds.reference")} htmlFor={`${formId}-reference`} className="col-span-full">
            <Input
              id={`${formId}-reference`}
              value={reference}
              maxLength={50}
              onChange={(event) => setReference(event.target.value)}
            />
          </Field>
        </div>
        <DialogFooter>
          <Button onClick={onClose}>{t("admin.refunds.cancel")}</Button>
          <Button variant="primary" disabled={pay.isPending} onClick={() => pay.mutate()}>
            {t("admin.refunds.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Trésorerie › Remboursements clients (D-284): the money credit notes give back to customers who had paid. Each
 * shows planned, refunded and left; "Rembourser" pays all or part of what is left from a caisse or a bank account.
 */
export function RefundsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canPay = session.role === "owner" || session.role === "manager";
  const [filter, setFilter] = useUrlState("statut", "open");
  const [search, setSearch] = useUrlState("q");
  const query = useDebounced(search.trim());
  const [paying, setPaying] = useState<CustomerRefund | null>(null);
  const list = useListCustomerRefunds(
    {
      ...(filter !== "all" ? { status: filter as ListCustomerRefundsStatus } : {}),
      ...(query ? { search: query } : {}),
    },
    { query: { placeholderData: keepPreviousData } },
  );
  const rows = list.data ?? [];

  return (
    <>
      <TresorerieRibbon active="remboursements" />
      <PageHeader eyebrow={t("admin.refunds.eyebrow")} title={t("admin.refunds.title")} />
      <p className="text-ink-2">{t("admin.refunds.intro")}</p>
      <Card className="flex flex-wrap items-center gap-3">
        <Input
          type="search"
          aria-label={t("admin.refunds.search")}
          placeholder={t("admin.refunds.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div role="group" aria-label={t("admin.refunds.statusFilter")} className="flex flex-wrap gap-1">
          {FILTERS.map((value) => (
            <Button
              key={value}
              variant={filter === value ? "primary" : "ghost"}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {t(`admin.refunds.filters.${value}`)}
            </Button>
          ))}
        </div>
      </Card>
      <Card>
        {list.isPending ? (
          <p className="text-ink-2">{t("common.loading")}</p>
        ) : rows.length === 0 ? (
          <EmptyState illustration="mix" title={t("admin.refunds.empty")} />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.refunds.columns.number")}</Th>
                <Th>{t("admin.refunds.columns.date")}</Th>
                <Th>{t("admin.refunds.columns.customer")}</Th>
                <Th>{t("admin.refunds.columns.documents")}</Th>
                <Th numeric>{t("admin.refunds.columns.amount")}</Th>
                <Th numeric>{t("admin.refunds.columns.refunded")}</Th>
                <Th numeric>{t("admin.refunds.columns.left")}</Th>
                <Th>{t("admin.refunds.columns.status")}</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <Td className="num font-semibold">{row.number}</Td>
                  <Td className="num">{formatDate(row.created_at)}</Td>
                  <Td>
                    {row.customer.name}
                    <div className="num text-[0.8rem] text-ink-2">{row.customer.reference}</div>
                  </Td>
                  <Td className="num text-[0.85rem]">
                    <Link to={`/factures/${row.invoice.id}`} className="font-semibold text-sea hover:underline">
                      {row.invoice.number}
                    </Link>
                    <div className="text-ink-2">{row.credit_note.number}</div>
                  </Td>
                  <Td numeric>{formatMoney(row.amount)}</Td>
                  <Td numeric>{formatMoney(row.refunded)}</Td>
                  <Td numeric className="font-semibold">
                    {formatMoney(row.left)}
                  </Td>
                  <Td>
                    <Pill tone={TONES[row.status]}>{t(`admin.refunds.statuses.${row.status}`)}</Pill>
                    {row.payments.map((payment) => (
                      <div key={payment.id} className="num text-[0.78rem] text-ink-2">
                        {formatDate(payment.paid_on)} · {t(`admin.refunds.methods.${payment.method}`)} ·{" "}
                        {payment.account_name} · {formatMoney(payment.amount)}
                      </div>
                    ))}
                  </Td>
                  <Td className="text-end">
                    {canPay && row.status !== "refunded" && (
                      <Button onClick={() => setPaying(row)}>{t("admin.refunds.pay")}</Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {paying && <PayDialog refund={paying} onClose={() => setPaying(null)} />}
    </>
  );
}
