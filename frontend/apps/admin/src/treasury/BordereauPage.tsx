import { type Instrument, useListBanks, useListInstruments } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, PageHeader } from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { useOutletContext } from "react-router";

import { sum } from "../lib/decimal";
import { canCollect } from "../payments/shared";
import { type Step, StepDialog } from "./PortfolioPage";
import { TAB_QUERY } from "./portfolio";
import { TresorerieRibbon } from "./TresorerieRibbon";

const PAGE_SIZE = 100;

/** The three columns of the bordereau de versement (Perfaxis): what is at the bank, what was cashed, what came back. */
type Column = "atBank" | "cashed" | "unpaid";

const COLUMNS: readonly Column[] = ["atBank", "cashed", "unpaid"];

/** What each column offers on the effets ticked in it: at the bank, cashed or unpaid; a cashed effet can still come
 * back unpaid; an unpaid one goes back to its drawer (Restituer). */
const ACTIONS: Record<Column, readonly Step[]> = {
  atBank: ["cash", "unpaid"],
  cashed: ["unpaid"],
  unpaid: ["return"],
};

/** "Bordereau de versement" (P9-T08): the cheques and traites handed to the bank, by where they stand. Tick effets in
 * a column, then act on them; the same rules and the same dialogs as the Portefeuille page. */
export function BordereauPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canWrite = canCollect(session);
  const banks = useListBanks();
  const [ticked, setTicked] = useState<Record<number, Instrument>>({});
  const [action, setAction] = useState<{ step: Step; effets: Instrument[] } | null>(null);

  const atBank = useListInstruments(
    { ...TAB_QUERY.atBank, limit: PAGE_SIZE },
    { query: { placeholderData: keepPreviousData } },
  );
  const cashed = useListInstruments(
    { ...TAB_QUERY.cashed, limit: PAGE_SIZE },
    { query: { placeholderData: keepPreviousData } },
  );
  const unpaid = useListInstruments(
    { ...TAB_QUERY.unpaid, limit: PAGE_SIZE },
    { query: { placeholderData: keepPreviousData } },
  );
  const rows: Record<Column, readonly Instrument[]> = {
    atBank: atBank.data?.results ?? [],
    cashed: cashed.data?.results ?? [],
    unpaid: unpaid.data?.results ?? [],
  };

  const toggle = (row: Instrument) =>
    setTicked((current) => {
      const next = { ...current };
      if (next[row.id]) delete next[row.id];
      else next[row.id] = row;
      return next;
    });
  const finish = () => {
    setAction(null);
    setTicked({});
  };

  return (
    <>
      <TresorerieRibbon active="bordereau" />
      <PageHeader eyebrow={t("admin.groups.finance")} title={t("admin.treasury.bordereau.title")} />
      <p className="text-ink-2">{t("admin.treasury.bordereau.intro")}</p>

      <div className="grid gap-4 lg:grid-cols-3">
        {COLUMNS.map((column) => {
          const picked = rows[column].filter((row) => ticked[row.id]);
          return (
            <Card key={column} className="flex flex-col gap-3 p-3">
              <div className="flex items-baseline justify-between gap-2">
                <CardTitle>{t(`admin.treasury.bordereau.columns.${column}`)}</CardTitle>
                <span className="num text-[0.9rem] text-ink-2">
                  {t("admin.treasury.bordereau.total", {
                    amount: formatMoney(sum(rows[column].map((row) => row.amount))),
                  })}
                </span>
              </div>

              {rows[column].length === 0 ? (
                <p className="text-ink-2">{t("admin.treasury.bordereau.empty")}</p>
              ) : (
                <ul className="flex flex-col divide-y divide-line">
                  {rows[column].map((row) => (
                    <li key={row.id}>
                      <label className="flex cursor-pointer items-center gap-3 py-2">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-sea"
                          checked={Boolean(ticked[row.id])}
                          onChange={() => toggle(row)}
                          aria-label={t("admin.treasury.bordereau.pick", { number: row.number })}
                        />
                        <span className="min-w-0 flex-1 text-[0.9rem]">
                          <span className="num font-semibold">{row.number}</span>
                          {` · ${t(`admin.treasury.bordereau.kinds.${row.kind}`)} · ${row.drawer || "—"}`}
                          {row.bank ? ` · ${row.bank.code}` : ""}
                          <span className="block text-[0.8rem] text-ink-2">{formatDate(row.due_on)}</span>
                        </span>
                        <span className="num font-semibold">{formatMoney(row.amount)}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}

              {canWrite && (
                <div className="flex flex-wrap gap-2">
                  {ACTIONS[column].map((step) => (
                    <Button
                      key={step}
                      variant="secondary"
                      disabled={picked.length === 0}
                      onClick={() => setAction({ step, effets: picked })}
                    >
                      {t(`admin.treasury.bordereau.actions.${step}`)}
                    </Button>
                  ))}
                </div>
              )}
            </Card>
          );
        })}
      </div>

      {action && (
        <StepDialog
          step={action.step}
          effets={action.effets}
          banks={banks.data ?? []}
          onClose={() => setAction(null)}
          onDone={finish}
        />
      )}
    </>
  );
}
