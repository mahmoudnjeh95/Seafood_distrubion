import {
  getExportAccountStatementUrl,
  type MovementRow,
  useGetAccountStatement,
  useListTreasuryAccounts,
} from "@frutti/api";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Card,
  Field,
  Input,
  PageHeader,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  Td,
  Th,
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { subtract } from "../lib/decimal";
import { useDebounced } from "../lib/useDebounced";
import { compare } from "../purchasing/allocation";
import { TresorerieRibbon } from "./TresorerieRibbon";

type Kind = "bank" | "cash";

/** "Journal des banques" and "Journal des caisses" (P9-T08): the movements of one account, in order, with the running
 * balance; the opening and closing balances frame the period. */
export function JournalPage({ kind }: { kind: Kind }) {
  const { t } = useTranslation();
  const accounts = useListTreasuryAccounts({ active_only: false });
  const choices = (accounts.data ?? []).filter((one) => one.kind === kind);
  // `?compte=3` (from a payment or a sale, "Où est l'argent") opens that account; else the first of the kind.
  const [urlParams] = useSearchParams();
  const [chosen, setChosen] = useState(urlParams.get("compte") ?? "");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [search, setSearch] = useState("");
  const query = useDebounced(search.trim());
  const account = choices.find((one) => String(one.id) === chosen) ?? choices[0];

  const params = {
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    ...(query ? { search: query } : {}),
  };
  const statement = useGetAccountStatement(account?.id ?? 0, params, {
    query: { enabled: account !== undefined, placeholderData: keepPreviousData },
  });
  const data = statement.data;

  return (
    <>
      <TresorerieRibbon active={kind === "bank" ? "journalBanques" : "journalCaisses"} />
      <PageHeader eyebrow={t("admin.groups.finance")} title={t(`admin.treasury.journal.${kind}.title`)}>
        {account && (
          <a
            href={getExportAccountStatementUrl(account.id, params)}
            download
            className="inline-flex items-center rounded-control border border-line bg-surface px-[15px] py-[9px] text-[0.9rem] font-semibold text-ink hover:bg-surface-2"
          >
            {t("admin.treasury.journal.export")}
          </a>
        )}
      </PageHeader>
      <p className="text-ink-2">{t(`admin.treasury.journal.${kind}.intro`)}</p>

      {choices.length === 0 ? (
        <Card className="p-3 text-ink-2">{t("admin.treasury.journal.noAccount")}</Card>
      ) : (
        <>
          <Card className="grid gap-3 p-3 md:grid-cols-[2fr_1fr_1fr_2fr]">
            <Field label={t("admin.treasury.journal.account")} htmlFor="journal-account">
              <Select value={account ? String(account.id) : ""} onValueChange={setChosen}>
                <SelectTrigger id="journal-account">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {choices.map((one) => (
                    <SelectItem key={one.id} value={String(one.id)}>
                      {one.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label={t("admin.treasury.journal.from")} htmlFor="journal-from">
              <Input
                id="journal-from"
                type="date"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </Field>
            <Field label={t("admin.treasury.journal.to")} htmlFor="journal-to">
              <Input id="journal-to" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
            </Field>
            <Field label={t("admin.treasury.journal.search")} htmlFor="journal-search">
              <Input id="journal-search" value={search} onChange={(event) => setSearch(event.target.value)} />
            </Field>
          </Card>

          {data && (
            <dl className="grid grid-cols-2 gap-3 rounded-card border border-line bg-surface p-3 shadow-card md:grid-cols-4">
              <Figure label={t("admin.treasury.journal.summary.opening")} value={formatMoney(data.opening)} />
              <Figure label={t("admin.treasury.journal.summary.totalIn")} value={formatMoney(data.total_in)} />
              <Figure label={t("admin.treasury.journal.summary.totalOut")} value={formatMoney(data.total_out)} />
              <Figure label={t("admin.treasury.journal.summary.closing")} value={formatMoney(data.closing)} />
            </dl>
          )}

          <Card className="p-2">
            {!data ? (
              <p className="p-2 text-ink-2">{t("common.loading")}</p>
            ) : data.rows.length === 0 ? (
              <p className="p-2 text-ink-2">{t("admin.treasury.journal.empty")}</p>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>{t("admin.treasury.journal.columns.day")}</Th>
                    <Th>{t("admin.treasury.journal.columns.label")}</Th>
                    <Th>{t("admin.treasury.journal.columns.reference")}</Th>
                    <Th numeric>{t("admin.treasury.journal.columns.in")}</Th>
                    <Th numeric>{t("admin.treasury.journal.columns.out")}</Th>
                    <Th numeric>{t("admin.treasury.journal.columns.balance")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <MovementLine key={row.id} row={row} />
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </>
      )}
    </>
  );
}

function MovementLine({ row }: { row: MovementRow }) {
  const { t } = useTranslation();
  const incoming = compare(row.amount, "0") > 0;
  return (
    <tr>
      <Td className="num whitespace-nowrap">{formatDate(row.day)}</Td>
      <Td>
        <span className="font-semibold">{t(`admin.treasury.journal.kinds.${row.kind}`)}</span>
        {row.description && <span className="text-ink-2"> · {row.description}</span>}
      </Td>
      <Td className="num">{row.reference || "—"}</Td>
      <Td numeric className="num">
        {incoming ? formatMoney(row.amount) : ""}
      </Td>
      <Td numeric className="num">
        {incoming ? "" : formatMoney(subtract("0", row.amount))}
      </Td>
      <Td numeric className="num font-semibold">
        {formatMoney(row.balance)}
      </Td>
    </tr>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className="num font-bold">{value}</dd>
    </div>
  );
}
