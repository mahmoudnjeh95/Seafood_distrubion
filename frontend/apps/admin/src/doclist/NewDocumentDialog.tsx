import type { WebRequest } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { type ComponentType, type KeyboardEvent, type MouseEvent, useRef, useState } from "react";

import { EmbeddedContext } from "../lib/embedded";
import { PurchaseOrderFormPage } from "../orders/PurchaseOrderFormPage";
import { SupplierInvoiceFormPage } from "../purchasing/SupplierInvoiceFormPage";
import { QuoteFormPage } from "../quotes/QuoteFormPage";
import { ReceiptFormPage } from "../receipts/ReceiptFormPage";
import { CounterSalePage } from "../sales/CounterSalePage";
import { SaleFormPage } from "../sales/SaleFormPage";

export type NewDocumentKind = "quote" | "sale" | "counter" | "order" | "receipt" | "supplierInvoice";

// The creation screens of each kind, shown as they are on their own page; they learn they are in a window
// through `EmbeddedContext` (D-138). Only a quote takes `fromRequest`: a site request's products (D-186).
const FORMS: Record<NewDocumentKind, ComponentType<{ fromRequest?: WebRequest }>> = {
  quote: QuoteFormPage,
  sale: SaleFormPage,
  counter: CounterSalePage,
  order: PurchaseOrderFormPage,
  receipt: ReceiptFormPage,
  supplierInvoice: SupplierInvoiceFormPage,
};

// A pick from a Radix select: its list is a portal, but React events still reach the window.
const isPick = (target: EventTarget) => target instanceof Element && target.closest('[role="option"]') !== null;

/**
 * "Nouveau document" on the Documents page (D-138): the creation form opens in a window over the list, so the
 * person never leaves it. Closing it, saved or not, refreshes the list. Escape or a click outside asks first when
 * something was typed or picked and not saved yet (the Annuler button closes at once). Closed while `kind` is null.
 */
export function NewDocumentDialog({
  kind,
  title,
  fromRequest,
  onClose,
}: {
  kind: NewDocumentKind | null;
  title: string;
  fromRequest?: WebRequest;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  // Set by the first edit in the window, cleared when it closes; a ref, since nothing renders from it.
  const edited = useRef(false);
  const [askingDiscard, setAskingDiscard] = useState(false);
  const Form = kind ? FORMS[kind] : null;

  const close = () => {
    edited.current = false;
    setAskingDiscard(false);
    onClose();
    void queryClient.invalidateQueries();
  };
  const dismiss = (open: boolean) => {
    if (open) return;
    if (edited.current) setAskingDiscard(true);
    else close();
  };
  const markPick = (event: MouseEvent | KeyboardEvent) => {
    if (!isPick(event.target)) return;
    if ("key" in event && event.key !== "Enter" && event.key !== " ") return;
    edited.current = true;
  };

  return (
    <>
      <Dialog open={kind !== null} onOpenChange={dismiss}>
        <DialogContent
          className="w-[min(1100px,calc(100vw-2rem))]"
          onChangeCapture={() => {
            edited.current = true;
          }}
          onClickCapture={markPick}
          onKeyDownCapture={markPick}
        >
          <DialogTitle className="sr-only">{title}</DialogTitle>
          {Form && (
            <EmbeddedContext.Provider value={{ close }}>
              <Form fromRequest={fromRequest} />
            </EmbeddedContext.Provider>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={askingDiscard} onOpenChange={(open) => !open && setAskingDiscard(false)}>
        <DialogContent className="w-[min(420px,calc(100vw-2rem))]">
          <DialogTitle>{t("admin.docHub.discardTitle")}</DialogTitle>
          <DialogDescription>{t("admin.docHub.discardBody")}</DialogDescription>
          <DialogFooter>
            <Button onClick={() => setAskingDiscard(false)}>{t("admin.docHub.discardKeep")}</Button>
            <Button variant="danger" onClick={close}>
              {t("admin.docHub.discardConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
