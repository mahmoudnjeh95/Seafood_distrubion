import { type LocationBatch, useListLocationBatches, useListProductBatches } from "@frutti/api";
import { formatQuantity, useTranslation } from "@frutti/i18n";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@frutti/ui";

import { isShort, type Line } from "./lines";

// Radix Select has no empty choice: this value stands for the oldest lot first (FIFO, the default, D-121).
const AUTO_LOT = "fifo";

/**
 * The lot a row takes its kilos from first. With `room`, the lots of the row's product at that place (the counter
 * sale); without, its lots in every cold room, each with where it sits (quotes and sales, D-201). Oldest first: a
 * hint of where they sit and who supplied them, never printed on a devis or a BL. FIFO stays the default.
 * `onChange` gets the lot and the place that holds it ("" for FIFO).
 */
export function LotPicker({
  room,
  line,
  onChange,
}: {
  room?: string;
  line: Line;
  onChange: (batch: string, location: number | null) => void;
}) {
  const { t } = useTranslation();
  const atRoom = useListLocationBatches(Number(room), Number(line.product), {
    query: { enabled: room !== undefined && room !== "" && line.product !== "" },
  });
  const everywhere = useListProductBatches(Number(line.product), {
    query: { enabled: room === undefined && line.product !== "" },
  });
  if (!line.product) return null;
  const options: LocationBatch[] = (room === undefined ? everywhere.data : atRoom.data) ?? [];
  const chosen = options.find((option) => String(option.batch_id) === line.batch);
  return (
    <>
      <Select
        value={line.batch || AUTO_LOT}
        onValueChange={(value) => {
          const picked = options.find((option) => String(option.batch_id) === value);
          onChange(value === AUTO_LOT ? "" : value, picked?.location_id ?? null);
        }}
      >
        <SelectTrigger
          aria-label={t("admin.sales.counterSale.lot")}
          className="border-0 bg-transparent px-2.5 py-2 [&>span]:truncate"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={AUTO_LOT}>{t("admin.sales.counterSale.lotAuto")}</SelectItem>
          {options.map((option) => (
            <SelectItem key={`${option.batch_id}-${option.location_id}`} value={String(option.batch_id)}>
              {t(room === undefined ? "admin.sales.counterSale.lotChoiceWhere" : "admin.sales.counterSale.lotChoice", {
                batch: option.batch_number,
                supplier: option.supplier_name,
                quantity: formatQuantity(option.quantity),
                place: option.location_name,
              })}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {chosen && isShort(line.quantity, chosen.quantity) && (
        <p className="px-2.5 pb-1.5 text-[0.78rem] font-semibold text-bad">
          {t("admin.sales.counterSale.lotShort", { quantity: formatQuantity(chosen.quantity) })}
        </p>
      )}
    </>
  );
}
