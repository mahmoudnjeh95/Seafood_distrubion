import { useTranslation } from "@frutti/i18n";
import { Button, toast } from "@frutti/ui";
import { useState } from "react";

import {
  bluetoothAvailable,
  forgetPrinter,
  loadSettings,
  type PrinterSettings,
  printReceipt,
  printTest,
  saveSettings,
} from "./printer";
import { type ReceiptData, WIDTHS } from "./receipt";

const PAPER = { 32: "58 mm", 42: "75 mm", 48: "80 mm" } as const;

/** "Imprimer le reçu" on the small Bluetooth printer, with its settings (paper width, office copy) folded below. */
export function PrintButton({ receipt }: { receipt: ReceiptData }) {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<PrinterSettings>(loadSettings);
  const [busy, setBusy] = useState(false);
  const supported = bluetoothAvailable();

  const change = (next: PrinterSettings) => {
    setSettings(next);
    saveSettings(next);
  };

  const run = async (job: () => Promise<void>) => {
    setBusy(true);
    try {
      await job();
      toast.success(t("truck.print.done"));
    } catch (failure) {
      // The phone's picker closed without a choice: nothing to report.
      if (failure instanceof DOMException && failure.name === "NotFoundError") return;
      forgetPrinter();
      toast.error(t("truck.print.failed", { why: failure instanceof Error ? failure.message : "" }));
    } finally {
      setBusy(false);
    }
  };

  if (!supported) return <p className="text-sm text-ink-2">{t("truck.print.unsupported")}</p>;

  return (
    <div className="space-y-2">
      <Button
        size="lg"
        className="py-4 text-lg"
        disabled={busy}
        onClick={() => void run(() => printReceipt(receipt, settings))}
      >
        {busy ? t("truck.print.printing") : t("truck.print.button")}
      </Button>
      <details className="text-sm">
        <summary className="cursor-pointer py-1 text-ink-2">{t("truck.print.settings")}</summary>
        <div className="space-y-3 py-2">
          <label className="flex items-center justify-between gap-3">
            <span>{t("truck.print.paper")}</span>
            <select
              className="rounded-md border border-line bg-surface px-2 py-2"
              value={settings.cols}
              onChange={(event) => change({ ...settings, cols: Number(event.target.value) })}
            >
              {WIDTHS.map((cols) => (
                <option key={cols} value={cols}>
                  {PAPER[cols]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings.officeCopy}
              onChange={(event) => change({ ...settings, officeCopy: event.target.checked })}
            />
            <span>{t("truck.print.officeCopy")}</span>
          </label>
          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings.accents}
              onChange={(event) => change({ ...settings, accents: event.target.checked })}
            />
            <span>{t("truck.print.accents")}</span>
          </label>
          <div className="flex gap-2">
            <Button disabled={busy} onClick={() => void run(() => printTest(settings))}>
              {t("truck.print.test")}
            </Button>
            <Button variant="ghost" onClick={forgetPrinter}>
              {t("truck.print.change")}
            </Button>
          </div>
        </div>
      </details>
    </div>
  );
}
