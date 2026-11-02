import { useTranslation } from "@frutti/i18n";
import { Button } from "@frutti/ui";

/** A cash line at or above the cash limit (D-273): the server refused it until the person confirms. Shows its
 * message and the button that sends the same payment again, confirmed. */
export function CashLimitNotice({
  message,
  pending,
  onConfirm,
}: {
  message: string;
  pending: boolean;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-chip bg-warn-soft px-3 py-2 text-[0.88rem] font-semibold text-warn"
    >
      <span className="min-w-0 flex-1">{message}</span>
      <Button variant="primary" disabled={pending} onClick={onConfirm}>
        {t("admin.payments.cashLimit.confirm")}
      </Button>
    </div>
  );
}
