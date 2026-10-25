import { useTranslation } from "@frutti/i18n";
import { Card, CardTitle, Field } from "@frutti/ui";

type BelowMinimumReasonProps = {
  /** The filled rows whose price after the discount is under the product's minimum (D-163). */
  count: number;
  /** The owner and the manager may accept such a price, with a reason (D-193); the others must correct it. */
  canApprove: boolean;
  reason: string;
  onReason: (reason: string) => void;
  error?: string;
};

/** Shown under the lines of a quote or a sale only while a row is under the minimum price. */
export function BelowMinimumReason({ count, canApprove, reason, onReason, error }: BelowMinimumReasonProps) {
  const { t } = useTranslation();
  if (count === 0) return null;
  return (
    <Card className="flex flex-col gap-2">
      <CardTitle className="mb-0 text-bad">{t("admin.lines.floor.title")}</CardTitle>
      {canApprove ? (
        <Field label={t("admin.lines.floor.reason")} htmlFor="below-minimum-reason" error={error}>
          <input
            id="below-minimum-reason"
            maxLength={255}
            value={reason}
            onChange={(event) => onReason(event.target.value)}
            aria-invalid={error ? true : undefined}
            className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
          />
          <p className="text-[0.8rem] text-ink-2">{t("admin.lines.floor.reasonHint", { count })}</p>
        </Field>
      ) : (
        <p role="alert" className="text-[0.88rem] font-semibold text-bad">
          {t("admin.lines.floor.refused")}
        </p>
      )}
    </Card>
  );
}
