import { type LocationBatch, useListLocationBatches } from "@frutti/api";
import { formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Icon,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@frutti/ui";
import { useState } from "react";

import { fromThousandths, toThousandths } from "./decimal";
import { isShort, isZero, type Line, type LotPick } from "./lines";

/**
 * The lots a row takes its kilos from first. Lots of the row's product at this room, oldest first: a hint of
 * where they sit and who supplied them, never printed on a devis or a BL (D-121). Several lots may be picked,
 * each with the kilos to take from it; the rest comes from the oldest lot (FIFO, the default, D-208).
 */
export function LotCell({
  room,
  line,
  onChange,
  disabled = false,
}: {
  room: string;
  line: Line;
  onChange: (picks: LotPick[]) => void;
  // Lots cannot be picked here (a load from several cold rooms, D-215): the row takes the oldest lots.
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const batches = useListLocationBatches(Number(room), Number(line.product), {
    query: { enabled: room !== "" && line.product !== "" },
  });
  if (!line.product) return null;
  if (disabled) return <p className="px-2.5 py-2 text-ink-2">{t("admin.sales.counterSale.lotAuto")}</p>;
  const lots = batches.data ?? [];
  const lotOf = (batch: string) => lots.find((option) => String(option.batch_id) === batch);
  return (
    <>
      <button
        type="button"
        aria-label={t("admin.sales.counterSale.lot")}
        onClick={() => setOpen(true)}
        className="w-full truncate px-2.5 py-2 text-start"
      >
        {line.picks.length === 0
          ? t("admin.sales.counterSale.lotAuto")
          : line.picks
              .map((pick) =>
                t("admin.sales.counterSale.lotPicked", {
                  batch: lotOf(pick.batch)?.batch_number ?? "",
                  quantity: pick.quantity,
                }),
              )
              .join(" + ")}
      </button>
      {line.picks.map((pick) => {
        const lot = lotOf(pick.batch);
        return lot && isShort(pick.quantity, lot.quantity) ? (
          <p key={pick.batch} className="px-2.5 pb-1.5 text-[0.78rem] font-semibold text-bad">
            {t("admin.sales.counterSale.lotShort", { quantity: formatQuantity(lot.quantity) })}
          </p>
        ) : null;
      })}
      <Dialog open={open} onOpenChange={setOpen}>
        <LotsDialog
          lots={lots}
          quantity={line.quantity}
          picks={line.picks}
          onSave={(picks) => {
            onChange(picks);
            setOpen(false);
          }}
          onCancel={() => setOpen(false)}
        />
      </Dialog>
    </>
  );
}

/** The lots picked for one row, each with its kilos, and what the picks leave over for the oldest lot. */
function LotsDialog({
  lots,
  quantity,
  picks,
  onSave,
  onCancel,
}: {
  lots: LocationBatch[];
  quantity: string;
  picks: LotPick[];
  onSave: (picks: LotPick[]) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<LotPick[]>(picks.length > 0 ? picks : [{ batch: "", quantity: "" }]);
  const [problem, setProblem] = useState("");
  const weight = parseDecimalInput(quantity.trim(), 3);
  const kgOf = (row: LotPick) => parseDecimalInput(row.quantity.trim(), 3);
  const taken = rows.reduce((total, row) => {
    const kg = kgOf(row);
    return kg === null ? total : total + toThousandths(kg);
  }, 0n);

  function update(index: number, fields: Partial<LotPick>) {
    setRows(rows.map((row, at) => (at === index ? { ...row, ...fields } : row)));
  }

  function save() {
    const chosen = rows.filter((row) => row.batch !== "");
    const weights = chosen.map((row) => kgOf(row));
    if (weights.some((kg) => kg === null || isZero(kg) || kg.startsWith("-"))) {
      setProblem(t("admin.sales.counterSale.lotNoKg"));
      return;
    }
    if (weight !== null && taken > toThousandths(weight)) {
      setProblem(t("admin.sales.counterSale.lotTooMuch", { quantity: formatQuantity(weight) }));
      return;
    }
    onSave(chosen.map((row, index) => ({ batch: row.batch, quantity: weights[index] ?? "" })));
  }

  return (
    <DialogContent>
      <DialogTitle>{t("admin.sales.counterSale.lotsTitle")}</DialogTitle>
      <DialogDescription>{t("admin.sales.counterSale.lotsHint")}</DialogDescription>
      <div className="flex flex-col gap-3">
        {rows.map((row, index) => {
          const others = rows.filter((_, at) => at !== index).map((other) => other.batch);
          const lot = lots.find((option) => String(option.batch_id) === row.batch);
          return (
            <div key={index} className="flex flex-col gap-1">
              <div className="grid grid-cols-[1fr_7rem_auto] items-center gap-2">
                <Select value={row.batch} onValueChange={(batch) => update(index, { batch })}>
                  <SelectTrigger aria-label={t("admin.sales.counterSale.lot")}>
                    <SelectValue placeholder={t("admin.sales.form.choose")} />
                  </SelectTrigger>
                  <SelectContent>
                    {lots
                      .filter((option) => !others.includes(String(option.batch_id)))
                      .map((option) => (
                        <SelectItem key={option.batch_id} value={String(option.batch_id)}>
                          {t("admin.sales.counterSale.lotChoice", {
                            batch: option.batch_number,
                            supplier: option.supplier_name,
                            quantity: formatQuantity(option.quantity),
                          })}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <Input
                  aria-label={t("admin.sales.counterSale.lotKg")}
                  inputMode="decimal"
                  value={row.quantity}
                  onChange={(event) => update(index, { quantity: event.target.value })}
                />
                <Button
                  aria-label={t("admin.sales.counterSale.lotRemove")}
                  onClick={() => setRows(rows.filter((_, at) => at !== index))}
                >
                  <Icon name="trash" />
                </Button>
              </div>
              {lot && isShort(row.quantity, lot.quantity) && (
                <p className="text-[0.78rem] font-semibold text-bad">
                  {t("admin.sales.counterSale.lotShort", { quantity: formatQuantity(lot.quantity) })}
                </p>
              )}
            </div>
          );
        })}
      </div>
      <Button onClick={() => setRows([...rows, { batch: "", quantity: "" }])}>
        {t("admin.sales.counterSale.lotAdd")}
      </Button>
      {weight !== null && (
        <p className={cn("text-[0.9rem] text-ink-2", taken > toThousandths(weight) && "font-semibold text-bad")}>
          {taken > toThousandths(weight)
            ? t("admin.sales.counterSale.lotTooMuch", { quantity: formatQuantity(weight) })
            : t("admin.sales.counterSale.lotRest", {
                quantity: formatQuantity(fromThousandths(toThousandths(weight) - taken)),
              })}
        </p>
      )}
      {problem && (
        <p role="alert" className="text-bad">
          {problem}
        </p>
      )}
      <DialogFooter className="items-center">
        <Button onClick={onCancel}>{t("admin.sales.counterSale.lotCancel")}</Button>
        <Button variant="primary" onClick={save}>
          {t("admin.sales.counterSale.lotSave")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
