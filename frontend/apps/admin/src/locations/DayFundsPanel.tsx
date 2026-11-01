import { type DayFundRow, setDayFund, useListDayFunds } from "@frutti/api";
import { formatDateTime, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, Field, Input, MoneyInput, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { fieldErrors } from "../lib/errors";

/** Today's date in the browser, as the `YYYY-MM-DD` the date input and the API use. */
function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** One driver's row: the cash typed by the office, saved on its own button. */
function FundRow({ row, date, canEdit }: { row: DayFundRow; date: string; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [cash, setCash] = useState(row.fund ? row.fund.opening_cash : "");
  const [float, setFloat] = useState(row.fund ? row.fund.purchase_float : "0");
  const [error, setError] = useState("");
  const locked = row.started || row.fund?.accepted_at != null;
  const cashValue = parseDecimalInput(cash.trim(), 3);
  const floatValue = row.can_buy ? parseDecimalInput(float.trim() || "0", 3) : "0";
  const save = useMutation({
    mutationFn: () =>
      setDayFund({
        driver: row.driver.id,
        date,
        opening_cash: cashValue ?? "0",
        purchase_float: floatValue ?? "0",
      }),
    onSuccess: async () => {
      setError("");
      toast.success(t("admin.dayFunds.saved", { name: row.driver.name }));
      await queryClient.invalidateQueries({
        predicate: (query) =>
          typeof query.queryKey[0] === "string" && query.queryKey[0].startsWith("/api/v1/day-funds"),
      });
    },
    onError: (failure) => setError(Object.values(fieldErrors(failure))[0] ?? t("admin.dayFunds.failed")),
  });
  const name = row.driver.name;
  return (
    <tr>
      <Td className="font-semibold">{name}</Td>
      <Td>
        {locked || !canEdit ? (
          <span className="num">{row.fund ? formatMoney(row.fund.opening_cash) : "—"}</span>
        ) : (
          <MoneyInput
            aria-label={t("admin.dayFunds.cashOf", { name })}
            inputMode="decimal"
            className="num max-w-36"
            value={cash}
            onChange={(event) => setCash(event.target.value)}
          />
        )}
      </Td>
      <Td>
        {!row.can_buy ? (
          <span className="text-ink-2">—</span>
        ) : locked || !canEdit ? (
          <span className="num">{row.fund ? formatMoney(row.fund.purchase_float) : "—"}</span>
        ) : (
          <MoneyInput
            aria-label={t("admin.dayFunds.floatOf", { name })}
            inputMode="decimal"
            className="num max-w-36"
            value={float}
            onChange={(event) => setFloat(event.target.value)}
          />
        )}
      </Td>
      <Td>
        {row.fund?.accepted_at ? (
          <Pill tone="good">{t("admin.dayFunds.accepted", { when: formatDateTime(row.fund.accepted_at) })}</Pill>
        ) : row.started ? (
          <Pill tone="neutral">{t("admin.dayFunds.started")}</Pill>
        ) : row.fund ? (
          <Pill tone="warn">{t("admin.dayFunds.waiting")}</Pill>
        ) : (
          <Pill tone="bad">{t("admin.dayFunds.notSet")}</Pill>
        )}
        {error && <p className="mt-1 text-[0.78rem] font-semibold text-bad">{error}</p>}
      </Td>
      <Td>
        {canEdit && !locked && (
          <Button
            variant="primary"
            disabled={cashValue === null || cashValue.startsWith("-") || floatValue === null || save.isPending}
            onClick={() => save.mutate()}
          >
            {t("admin.dayFunds.save")}
          </Button>
        )}
      </Td>
    </tr>
  );
}

/**
 * "Fonds de caisse du jour" (D-203): the office types the cash it hands each driver (and the money for the port);
 * the driver accepts it on the phone, which starts the day. A row no longer changes once accepted.
 */
export function DayFundsPanel({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const dateId = useId();
  const [date, setDate] = useState(todayIso);
  const funds = useListDayFunds({ date });
  const rows = funds.data ?? [];
  return (
    <section aria-label={t("admin.dayFunds.title")} className="flex flex-col gap-3">
      <h2>{t("admin.dayFunds.title")}</h2>
      <p className="text-ink-2">{t("admin.dayFunds.intro")}</p>
      <div className="max-w-[220px]">
        <Field label={t("admin.dayFunds.date")} htmlFor={dateId}>
          <Input
            id={dateId}
            type="date"
            value={date}
            onChange={(event) => event.target.value && setDate(event.target.value)}
          />
        </Field>
      </div>
      {rows.length === 0 ? (
        <p className="text-ink-2">{t(funds.isPending ? "common.loading" : "admin.dayFunds.noDrivers")}</p>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.dayFunds.driver")}</Th>
                <Th>{t("admin.dayFunds.cash")}</Th>
                <Th>{t("admin.dayFunds.float")}</Th>
                <Th>{t("admin.dayFunds.state")}</Th>
                <Th>{null}</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <FundRow
                  key={`${date}-${row.driver.id}-${row.fund?.set_at ?? ""}`}
                  row={row}
                  date={date}
                  canEdit={canEdit}
                />
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </section>
  );
}
