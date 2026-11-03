import { useGetMyReceiptHeader } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, toast } from "@frutti/ui";
import { useEffect, useState } from "react";

import { rememberedLogo } from "../companyLogo";

import {
  bluetoothAvailable,
  forgetPrinter,
  loadSettings,
  type PrinterSettings,
  printReceipt,
  printTest,
  saveSettings,
} from "./printer";
import { drawReceipt } from "./raster";
import { layoutReceipt, previewText, type ReceiptCopy, type ReceiptData, WIDTHS } from "./receipt";

const PAPER = { 32: "58 mm", 42: "75 mm", 48: "80 mm" } as const;

/** The seller printed at the top (D-281): the finance settings, kept by the phone for printing without signal. */
function useWithSeller(receipt: ReceiptData): ReceiptData {
  const header = useGetMyReceiptHeader({ query: { staleTime: 60 * 60_000, retry: false } });
  if (header.data === undefined) return receipt;
  return {
    ...receipt,
    company: header.data.name || receipt.company,
    seller: { address: header.data.address, phone: header.data.phone, taxId: header.data.tax_id },
  };
}

/**
 * "Imprimer le reçu" on the small Bluetooth printer (D-278). One copy per tap (D-281): the first tap prints the
 * customer's or supplier's receipt, the next one the office copy; after that each can be printed again. The
 * settings (paper width, accents) and a preview of the paper are folded below.
 */
export function PrintButton({ receipt }: { receipt: ReceiptData }) {
  const { t } = useTranslation();
  const data = useWithSeller(receipt);
  const [settings, setSettings] = useState<PrinterSettings>(loadSettings);
  const [busy, setBusy] = useState(false);
  const [printed, setPrinted] = useState<ReceiptCopy[]>([]);
  // The preview picture, drawn only while the preview is open.
  const [showing, setShowing] = useState(false);
  const [picture, setPicture] = useState<string | null>(null);
  const supported = bluetoothAvailable();
  const supplier = receipt.kind === "purchase";

  const change = (next: PrinterSettings) => {
    setSettings(next);
    saveSettings(next);
  };

  const run = async (job: () => Promise<void>, copy?: ReceiptCopy) => {
    setBusy(true);
    try {
      await job();
      if (copy === undefined) {
        toast.success(t("truck.print.done"));
        return;
      }
      const after = printed.includes(copy) ? printed : [...printed, copy];
      setPrinted(after);
      if (copy === "party" && !after.includes("office")) {
        toast.success(t(supplier ? "truck.print.officeNextSupplier" : "truck.print.officeNext"));
      } else if (after.length === 2 && printed.length < 2) {
        toast.success(t("truck.print.bothDone"));
      } else {
        toast.success(t("truck.print.done"));
      }
    } catch (failure) {
      // The phone's picker closed without a choice: nothing to report.
      if (failure instanceof DOMException && failure.name === "NotFoundError") return;
      forgetPrinter();
      toast.error(t("truck.print.failed", { why: failure instanceof Error ? failure.message : "" }));
    } finally {
      setBusy(false);
    }
  };

  const print = (copy: ReceiptCopy) => void run(() => printReceipt(data, copy, settings), copy);
  // The main button: the customer's (or supplier's) copy first, then the office's, then the customer's again.
  const next: ReceiptCopy = printed.includes("party") && !printed.includes("office") ? "office" : "party";
  const other: ReceiptCopy = next === "party" ? "office" : "party";
  const label = (copy: ReceiptCopy) => {
    if (copy === "office") return t(printed.includes("office") ? "truck.print.againOffice" : "truck.print.office");
    if (printed.includes("party")) return t(supplier ? "truck.print.againPartySupplier" : "truck.print.againParty");
    return t(supplier ? "truck.print.partySupplier" : "truck.print.party");
  };

  const rows = layoutReceipt(data, next, settings.cols);
  const text = previewText(rows, settings.cols);
  const drawn = showing && settings.picture;
  useEffect(() => {
    if (!drawn) return;
    let gone = false;
    drawReceipt(layoutReceipt(data, next, settings.cols), settings.cols, rememberedLogo())
      .then((canvas) => {
        if (!gone) setPicture(canvas.toDataURL());
      })
      .catch(() => {
        if (!gone) setPicture(null);
      });
    return () => {
      gone = true;
    };
    // `text` stands for the rows: the picture is drawn again when what it shows changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawn, text, settings.cols]);
  const preview = (
    <details className="text-sm" onToggle={(event) => setShowing(event.currentTarget.open)}>
      <summary className="cursor-pointer py-1 text-ink-2">{t("truck.print.preview")}</summary>
      {settings.picture && picture !== null ? (
        // The picture the printer gets, logo and Arabic names included (D-282).
        <img
          src={picture}
          alt={t("truck.print.preview")}
          className="mx-auto w-full max-w-xs border border-line bg-white"
        />
      ) : (
        <pre className="overflow-x-auto rounded-control border border-line bg-surface p-2 font-mono text-xs leading-snug">
          {text}
        </pre>
      )}
    </details>
  );

  if (!supported) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-ink-2">{t("truck.print.unsupported")}</p>
        {preview}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Button size="lg" className="w-full py-4 text-lg" disabled={busy} onClick={() => print(next)}>
        {busy ? t("truck.print.printing") : label(next)}
      </Button>
      {/* Once the first copy is out, the other one can be printed (again) without going through the cycle. */}
      {printed.length > 0 ? (
        <Button variant="ghost" className="w-full" disabled={busy} onClick={() => print(other)}>
          {label(other)}
        </Button>
      ) : null}
      {preview}
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
              checked={settings.picture}
              onChange={(event) => change({ ...settings, picture: event.target.checked })}
            />
            <span>{t("truck.print.picture")}</span>
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
