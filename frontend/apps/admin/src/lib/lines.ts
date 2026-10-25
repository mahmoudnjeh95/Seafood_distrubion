// The rows of a sale, a quote or a counter sale as a person types them in the grid (`LinesGrid`, D-139).

import { parseDecimalInput } from "@frutti/i18n";

import { lineTotal, percentOf, subtract, toThousandths } from "./decimal";

export type Line = {
  key: number;
  product: string;
  quantity: string;
  unit_price: string;
  discount_rate: string;
  // Once a person types a price, the row stops showing the price in force.
  priceTouched: boolean;
  // The lot a counter sale takes the kilos from first; empty for the oldest one (FIFO, D-121).
  batch: string;
};

export type Amounts = { gross: string; discount: string; amount: string };

// Gives each row a stable React key, also for rows not saved yet.
let nextKey = 0;
export function newLine(fields: Partial<Omit<Line, "key">> = {}): Line {
  nextKey += 1;
  return {
    key: nextKey,
    product: "",
    quantity: "",
    unit_price: "",
    discount_rate: "",
    priceTouched: false,
    batch: "",
    ...fields,
  };
}

// The API writes "20.250"; people here write "20,250". Both are read back by parseDecimalInput.
export const asTyped = (value: string) => value.replace(".", ",");
// "5.00" is shown as "5", "2.50" as "2,5": a rate is typed like a person writes it.
export const rateAsTyped = (value: string) => asTyped(value.replace(/\.?0+$/, ""));
export const isZero = (value: string) => /^0+(\.0+)?$/.test(value);

/** Nothing chosen and nothing typed: the spare row at the end of the grid, or a row emptied by hand. */
export function isBlank(line: Line): boolean {
  const typedPrice = line.priceTouched && line.unit_price.trim() !== "";
  return !line.product && line.quantity.trim() === "" && line.discount_rate.trim() === "" && !typedPrice;
}

/** The rows that are sent to the server: the blank ones are only places to type in. */
export const filled = (lines: readonly Line[]) => lines.filter((line) => !isBlank(line));

/** The same rows ending with exactly one blank row, so there is always a place to type the next product. */
export function withSpare(lines: Line[]): Line[] {
  let used = lines.length;
  while (used > 0 && isBlank(lines[used - 1]!)) used -= 1;
  if (used === lines.length) return [...lines, newLine()];
  return used + 1 === lines.length ? lines : lines.slice(0, used + 1);
}

/** What the price cell shows: the price typed, or else the price the customer is charged (`proposed`). */
export function shownPrice(line: Line, proposed: string | null): string {
  if (line.priceTouched) return line.unit_price;
  return proposed ? asTyped(proposed) : "";
}

/** Browser-side preview of the server's amounts for one row (D-050), or null while the row cannot be priced. */
export function amountsOf(line: Line, price: string): Amounts | null {
  const quantity = parseDecimalInput(line.quantity.trim(), 3);
  const unitPrice = parseDecimalInput(price.trim(), 3);
  const rate = line.discount_rate.trim() === "" ? "0" : parseDecimalInput(line.discount_rate.trim(), 2);
  if (!quantity || !unitPrice || !rate) return null;
  if ([quantity, unitPrice, rate].some((value) => value.startsWith("-"))) return null;
  const gross = lineTotal(quantity, unitPrice);
  const discount = percentOf(gross, rate);
  return { gross, discount, amount: subtract(gross, discount) };
}

/** The price per kg once the row's discount is taken off, when that is under the product's minimum (D-163), else null.
 * The server decides: this only warns while typing. */
export function netUnderMinimum(line: Line, price: string, minimum: string | null): string | null {
  if (!minimum) return null;
  const unit = parseDecimalInput(price.trim(), 3);
  const rate = line.discount_rate.trim() === "" ? "0" : parseDecimalInput(line.discount_rate.trim(), 2);
  if (!unit || !rate || unit.startsWith("-") || rate.startsWith("-")) return null;
  const net = subtract(unit, percentOf(unit, rate));
  return toThousandths(net) > 0n && toThousandths(net) < toThousandths(minimum) ? net : null;
}

/** True when more kilos are typed than the place holds; never when the stock is not known. */
export function isShort(typed: string, available: string | undefined): boolean {
  const quantity = parseDecimalInput(typed.trim(), 3);
  if (!quantity || available === undefined) return false;
  return toThousandths(quantity) > toThousandths(available);
}
