import { convertQuoteToSale, type QuoteDetail, useGetQuote, useListLocations } from "@frutti/api";
import { formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Input,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";

import { fieldErrors } from "../lib/errors";
import { choosePlace, type Need, usePlacesStock } from "../lib/placeStock";

const isZero = (value: string) => /^0+(\.0+)?$/.test(value);
// The API writes "2.000"; people here write "2" or "2,5".
const asTyped = (value: string) => value.replace(/\.?0+$/, "").replace(".", ",");

/**
 * "Convertir en vente": a BL made from an accepted quote. It proposes every kilo not on a BL yet; lowering a
 * weight leaves the rest for a later BL (D-115). Closed while `quoteId` is null. `stayHere` (D-192): inside a window
 * over another page, the BL is made without navigating to it.
 */
export function DeliverDialog({
  quoteId,
  onClose,
  stayHere = false,
}: {
  quoteId: number | null;
  onClose: () => void;
  stayHere?: boolean;
}) {
  const { t } = useTranslation();
  const quote = useGetQuote(quoteId ?? 0, { query: { enabled: quoteId !== null, retry: false } });
  const data = quoteId !== null && quote.data?.id === quoteId ? quote.data : undefined;

  return (
    <Dialog open={quoteId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {data ? (
          // Keyed: the weights start again from what is left each time the quote changes.
          <DeliverForm
            key={`${data.id}:${data.remaining_quantity}`}
            quote={data}
            onClose={onClose}
            stayHere={stayHere}
          />
        ) : (
          <>
            <DialogTitle>{t("admin.sales.fromQuote.convert")}</DialogTitle>
            <DialogDescription>{quote.isError ? t("common.serverUnreachable") : t("common.loading")}</DialogDescription>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DeliverForm({ quote, onClose, stayHere }: { quote: QuoteDetail; onClose: () => void; stayHere: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const open = quote.lines.filter((line) => !isZero(line.remaining_quantity));
  const [typed, setTyped] = useState<Record<number, string>>(() =>
    Object.fromEntries(open.map((line) => [line.id, asTyped(line.remaining_quantity)])),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const locations = useListLocations({ status: "active" });
  // The sale leaves from the one place that holds all the kilos typed here (D-144).
  const byPlace = usePlacesStock((locations.data ?? []).filter((option) => option.sells).map((option) => option.id));

  const convert = useMutation({
    mutationFn: ({
      confirmNow,
      lines,
      place,
    }: {
      confirmNow: boolean;
      lines: { quote_line: number; quantity: string }[];
      place: number;
    }) => convertQuoteToSale(quote.id, { location: place, confirm_now: confirmNow, lines }),
    onSuccess: async (sale) => {
      toast.success(t("admin.sales.fromQuote.created", { number: sale.number }));
      onClose();
      await queryClient.invalidateQueries();
      if (!stayHere) void navigate(`/ventes/${sale.id}`);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      const found: Record<string, string> = {};
      for (const [key, message] of Object.entries(fromServer)) {
        // `lines.<index>.quantity` is the index among the lines sent: the ones still open, in order.
        const match = /^lines\.(\d+)\./.exec(key);
        const line = match ? open[Number(match[1])] : undefined;
        if (line) found[`line.${line.id}`] = message;
        else found.detail = message;
      }
      setErrors(Object.keys(found).length > 0 ? found : { detail: t("admin.quotes.detail.actionError") });
    },
  });

  const submit = (confirmNow: boolean) => {
    const found: Record<string, string> = {};
    const lines: { quote_line: number; quantity: string }[] = [];
    const needs: Need[] = [];
    for (const line of open) {
      const text = (typed[line.id] ?? "").trim();
      const quantity = text === "" ? "0" : parseDecimalInput(text, 3);
      if (quantity === null || quantity.startsWith("-")) found[`line.${line.id}`] = t("admin.sales.fromQuote.invalid");
      else {
        lines.push({ quote_line: line.id, quantity });
        if (!isZero(quantity)) needs.push({ product: String(line.product.id), kg: quantity });
      }
    }
    if (Object.keys(found).length === 0 && lines.every((line) => isZero(line.quantity))) {
      found.detail = t("admin.sales.fromQuote.nothing");
    }
    const place = choosePlace(needs, byPlace);
    if (place === null && needs.length > 0) {
      const names = needs.map((need) => open.find((line) => String(line.product.id) === need.product)?.product.name);
      found.detail = t("admin.sales.form.noSinglePlace", { products: names.join(", ") });
    }
    setErrors(found);
    if (Object.keys(found).length === 0 && place !== null) convert.mutate({ confirmNow, lines, place });
  };

  return (
    <>
      <DialogTitle>{t("admin.sales.fromQuote.title", { number: quote.number })}</DialogTitle>
      <DialogDescription>{t("admin.sales.fromQuote.body")}</DialogDescription>
      <Table>
        <thead>
          <tr>
            <Th>{t("admin.quotes.detail.product")}</Th>
            <Th numeric>{t("admin.sales.fromQuote.remaining")}</Th>
            <Th numeric>{t("admin.sales.fromQuote.toDeliver")}</Th>
          </tr>
        </thead>
        <tbody>
          {quote.lines.map((line) => {
            const done = isZero(line.remaining_quantity);
            const error = errors[`line.${line.id}`];
            return (
              <tr key={line.id}>
                <Td>
                  {line.product.name}
                  <div className="num text-[0.8rem] text-ink-2">
                    {t("admin.sales.fromQuote.quoted", { quantity: formatQuantity(line.quantity) })}
                  </div>
                </Td>
                <Td numeric className="whitespace-nowrap">
                  {done ? t("admin.sales.fromQuote.delivered") : formatQuantity(line.remaining_quantity)}
                </Td>
                <Td numeric>
                  {!done && (
                    <>
                      <Input
                        inputMode="decimal"
                        aria-label={t("admin.sales.fromQuote.toDeliverOf", { product: line.product.name })}
                        aria-invalid={error ? true : undefined}
                        value={typed[line.id] ?? ""}
                        onChange={(event) => setTyped((current) => ({ ...current, [line.id]: event.target.value }))}
                        className="num ms-auto w-24 text-end"
                      />
                      {error && (
                        <p role="alert" className="mt-1 text-[0.8rem] text-bad">
                          {error}
                        </p>
                      )}
                    </>
                  )}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </Table>
      {errors.detail && (
        <p role="alert" className="text-[0.85rem] text-bad">
          {errors.detail}
        </p>
      )}
      <DialogFooter>
        <Button onClick={onClose}>{t("admin.quotes.detail.keep")}</Button>
        <Button disabled={convert.isPending} onClick={() => submit(false)}>
          {t("admin.sales.fromQuote.draft")}
        </Button>
        <Button variant="primary" disabled={convert.isPending} onClick={() => submit(true)}>
          {t("admin.sales.fromQuote.confirm")}
        </Button>
      </DialogFooter>
    </>
  );
}
