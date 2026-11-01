import type { Customer, Product } from "@frutti/api";
import { formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  Field,
  Icon,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@frutti/ui";
import { useId } from "react";

import { BoxCountsFields } from "../boxes/BoxCountsFields";
import { sum } from "../lib/decimal";
import { amountsOf, filled, type Line, shownPrice } from "../lib/lines";
import { lotColumn } from "../lib/lotColumn";
import { LinesGrid } from "../lib/LinesGrid";
import { pickable } from "../lib/pickable";
import type { PlaceKilos } from "../lib/placeStock";
import { addressOf, type Part, scopedErrors } from "./formLines";

/**
 * The part of a truck load that is for one client (D-160): who, where it is delivered (the client's address,
 * changeable for this load's BL only), what they buy and the boxes they get. Each client gets a BL of their own.
 * The products are typed in a grid like a sale's, with the client's price proposed (D-174).
 */
export function ClientPart({
  index,
  part,
  customers,
  products,
  proposedPrice,
  priceHint,
  stock,
  places,
  errors,
  lotRoom,
  onChange,
  onRemove,
}: {
  index: number;
  part: Part;
  customers: readonly Customer[];
  products: Product[];
  /** The price this client is charged for a product until one is typed: their own list, else the daily price. */
  proposedPrice: (product: string) => string | null;
  priceHint: (line: Line) => string;
  /** Kilos left for this client per product: the stock less what the other parts of the load take. */
  stock?: Map<string, string>;
  places?: Map<string, PlaceKilos[]>;
  errors: Record<string, string>;
  /** The place the kg leave from, where lots are picked; undefined when they cannot be (D-215). */
  lotRoom: string | undefined;
  onChange: (next: Part) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const formId = useId();
  const own = scopedErrors(errors, `deliveries.${index}.`);
  const id = (name: string) => `${formId}-${name}`;
  const customer = customers.find((candidate) => String(candidate.id) === part.customer);
  const total = sum(
    filled(part.lines).flatMap((line) => {
      const amounts = amountsOf(line, shownPrice(line, line.product ? proposedPrice(line.product) : null));
      return amounts ? [amounts.amount] : [];
    }),
  );

  return (
    <Card
      className="flex flex-col gap-3 border-sea/40"
      role="group"
      aria-label={t("admin.transfers.form.clientNumber", { number: index + 1 })}
    >
      <div className="flex flex-wrap items-center gap-3">
        <CardTitle className="mb-0">
          {customer?.name ?? t("admin.transfers.form.clientNumber", { number: index + 1 })}
        </CardTitle>
        <Button
          className="ms-auto"
          size="icon"
          variant="ghost"
          aria-label={t("admin.transfers.form.removeClient")}
          title={t("admin.transfers.form.removeClient")}
          onClick={onRemove}
        >
          <Icon name="trash" />
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-4 max-[800px]:grid-cols-1">
        <Field label={t("admin.transfers.form.client")} htmlFor={id("customer")} error={own.customer}>
          <Select
            value={part.customer}
            onValueChange={(value) =>
              onChange({
                ...part,
                customer: value,
                address: addressOf(customers.find((candidate) => String(candidate.id) === value)),
                // Another client has other prices: the rows show the new client's until a price is typed.
                lines: part.lines.map((line) => (line.priceTouched ? line : { ...line, unit_price: "" })),
              })
            }
          >
            <SelectTrigger id={id("customer")} aria-invalid={own.customer ? true : undefined}>
              <SelectValue placeholder={t("admin.transfers.form.choose")} />
            </SelectTrigger>
            <SelectContent>
              {pickable(
                customers.filter((candidate) => !candidate.is_walk_in),
                [part.customer],
              ).map((candidate) => (
                <SelectItem key={candidate.id} value={String(candidate.id)}>
                  {candidate.name} · {candidate.reference}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("admin.transfers.form.deliveryAddress")} htmlFor={id("address")} error={own.delivery_address}>
          <Input
            id={id("address")}
            value={part.address}
            maxLength={255}
            autoComplete="off"
            onChange={(event) => onChange({ ...part, address: event.target.value })}
          />
        </Field>
      </div>
      <p className="text-[0.85rem] text-ink-2">{t("admin.transfers.form.deliveryAddressHint")}</p>

      <LinesGrid
        label={t("admin.transfers.form.clientLines", { name: customer?.name ?? index + 1 })}
        lines={part.lines}
        onChange={(lines) => onChange({ ...part, lines })}
        products={products}
        proposedPrice={proposedPrice}
        stock={stock}
        places={places}
        errors={own}
        hint={priceHint}
        extra={lotColumn(t("admin.sales.counterSale.lot"), lotRoom)}
      />
      {own.lines && <p className="text-[0.78rem] font-semibold text-bad">{own.lines}</p>}
      <dl className="ms-auto text-end">
        <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.transfers.form.clientTotal")}</dt>
        <dd className="num font-bold">{formatMoney(total)}</dd>
      </dl>

      <BoxCountsFields
        title={t("admin.transfers.form.clientBoxesTitle")}
        hint={t("admin.transfers.form.clientBoxesHint")}
        value={part.boxes}
        onChange={(boxes) => onChange({ ...part, boxes })}
        errors={own}
      />
    </Card>
  );
}
