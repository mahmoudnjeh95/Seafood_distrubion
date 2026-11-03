import { type BankStatementLine, matchStatementLine, useListMatchCandidates } from "@frutti/api";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, Pill, toast } from "@frutti/ui";
import { useState } from "react";

import { subtract } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";

/** Rapprochement bancaire (D-265, provisional): the movements of our ledger that look like this line of the bank's
 * statement (same amount, within three days), or every movement of the month for a match by hand. The office
 * confirms one; nothing changes a balance. */
export function MatchDialog({
  line,
  onClose,
  onDone,
}: {
  line: BankStatementLine;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [byHand, setByHand] = useState(false);
  const [pending, setPending] = useState(false);
  const candidates = useListMatchCandidates(line.id, { by_hand: byHand });
  const wanted = subtract(line.debit, line.credit);
  const rows = candidates.data ?? [];

  async function confirm(movement: number) {
    setPending(true);
    try {
      await matchStatementLine(line.id, { movement });
      toast.success(t("admin.treasury.match.done"));
      await onDone();
    } catch (failure) {
      toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.treasury.match.error"));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{t("admin.treasury.match.title")}</DialogTitle>
        <DialogDescription>
          {t("admin.treasury.match.line", {
            day: formatDate(line.day),
            label: line.label,
            amount: formatMoney(wanted),
          })}
        </DialogDescription>
        {candidates.isPending ? (
          <p className="text-ink-2">{t("common.loading")}</p>
        ) : rows.length === 0 ? (
          <p className="text-ink-2">
            {byHand ? t("admin.treasury.match.noneByHand") : t("admin.treasury.match.noSuggestion")}
          </p>
        ) : (
          <ul className="flex max-h-72 flex-col divide-y divide-line overflow-y-auto">
            {rows.map(({ movement, suggested }) => {
              const gap = subtract(movement.amount, wanted);
              return (
                <li key={movement.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-[0.9rem]">
                  <span className="min-w-0 flex-1">
                    <span className="font-semibold">{movement.label}</span>
                    <span className="block text-[0.8rem] text-ink-2">
                      {formatDate(movement.day)}
                      {gap !== "0.000" && ` · ${t("admin.treasury.match.gap", { amount: formatMoney(gap) })}`}
                    </span>
                  </span>
                  {suggested && <Pill tone="good">{t("admin.treasury.match.suggested")}</Pill>}
                  <span className="num font-semibold">{formatMoney(movement.amount)}</span>
                  <Button disabled={pending} onClick={() => void confirm(movement.id)}>
                    {t("admin.treasury.match.confirm")}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => setByHand((current) => !current)}>
            {byHand ? t("admin.treasury.match.onlySuggestions") : t("admin.treasury.match.byHand")}
          </Button>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
