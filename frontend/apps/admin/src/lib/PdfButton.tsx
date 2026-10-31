import { useTranslation } from "@frutti/i18n";
import { Button, Icon, toast } from "@frutti/ui";
import { useState } from "react";

import { EmailButton } from "./EmailButton";
import { openPdf, PdfError, type PdfKind } from "./pdf";

/** "PDF": makes the document's PDF in the background and opens it when ready. Next to it, "E-mail" sends it from the
 * company address (D-206). */
export function PdfButton({
  kind,
  id,
  variant,
  className,
  label,
}: {
  kind: PdfKind;
  id: number;
  variant?: "primary" | "ghost" | "danger";
  className?: string;
  /** Text of the button when it is not just "PDF". */
  label?: string;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);

  const open = async () => {
    setBusy(true);
    try {
      await openPdf(kind, id);
    } catch (error) {
      const reason = error instanceof PdfError ? error.message : "";
      toast.error(
        reason && !["timeout", "failed", "refused"].includes(reason) && !reason.startsWith("status ")
          ? reason
          : t(reason === "timeout" ? "admin.documents.slow" : "admin.documents.failed"),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button variant={variant} className={className} disabled={busy} onClick={() => void open()}>
        <Icon name="receipt" />
        {busy ? t("admin.documents.making") : (label ?? t("admin.documents.pdf"))}
      </Button>
      <EmailButton kind={kind} id={id} className={className} />
    </>
  );
}
