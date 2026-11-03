import type { GoodsReceiptRevision, Receipt, ReceiptChange } from "@frutti/api";
import { formatDate, formatDateTime, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Card, CardTitle } from "@frutti/ui";

// The fields a change can name: the header's, then a line's (the server sends them as plain text).
const HISTORY_FIELDS = [
  "supplier_reference",
  "notes",
  "with_vat",
  "invoiced_quantity",
  "accepted_quantity",
  "unit_cost",
  "use_by",
] as const;
type HistoryField = (typeof HISTORY_FIELDS)[number];
const isHistoryField = (field: string): field is HistoryField => (HISTORY_FIELDS as readonly string[]).includes(field);

/** Every change made to a receipt after it was saved, newest first, each with what it changed (D-269). */
export function ReceiptHistory({ receipt }: { receipt: Receipt }) {
  const { t } = useTranslation();

  const shown = (field: string, value: string | null) => {
    if (value === null) return t("admin.receipts.history.empty");
    if (field === "invoiced_quantity" || field === "accepted_quantity") return formatQuantity(value);
    if (field === "unit_cost") return formatMoney(value);
    if (field === "use_by") return formatDate(value);
    return value;
  };

  const describe = (change: ReceiptChange) => {
    const label = isHistoryField(change.field) ? t(`admin.receipts.history.fields.${change.field}`) : change.field;
    const product = change.line === null ? undefined : receipt.lines[change.line]?.product.name;
    const what = product ? t("admin.receipts.history.line", { product, field: label }) : label;
    return `${what} : ${shown(change.field, change.before)} → ${shown(change.field, change.after)}`;
  };

  const revisions: GoodsReceiptRevision[] = [...receipt.revisions].reverse();
  return (
    <Card>
      <CardTitle>{t("admin.receipts.history.title")}</CardTitle>
      {revisions.length === 0 ? (
        <p className="text-ink-2">{t("admin.receipts.history.none")}</p>
      ) : (
        <ol className="flex flex-col gap-4">
          {revisions.map((revision) => (
            <li key={revision.number} className="flex flex-col gap-1 border-s-2 border-line ps-3">
              <div className="flex flex-wrap items-center gap-2">
                <b>{t("admin.receipts.history.version", { number: revision.number })}</b>
                <span className="num text-[0.85rem] text-ink-2">{formatDateTime(revision.created_at)}</span>
                {revision.created_by && (
                  <span className="text-[0.85rem] text-ink-2">
                    {t("admin.receipts.history.by", { name: revision.created_by })}
                  </span>
                )}
              </div>
              <p className="whitespace-pre-line italic">« {revision.reason} »</p>
              {revision.changes.length > 0 && (
                <ul className="flex flex-col gap-0.5 text-[0.9rem]">
                  {revision.changes.map((change, index) => (
                    <li key={index}>{describe(change)}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
