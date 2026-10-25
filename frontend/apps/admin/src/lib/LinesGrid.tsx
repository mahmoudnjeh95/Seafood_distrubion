import type { Product } from "@frutti/api";
import { formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, cn, Combobox, type ComboboxOption, Icon, Pill, Table, Th } from "@frutti/ui";
import { type KeyboardEvent, type MouseEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { subtract, sum } from "./decimal";
import { amountsOf, filled, isBlank, isShort, type Line, netUnderMinimum, shownPrice, withSpare } from "./lines";
import type { PlaceKilos } from "./placeStock";

type Column = "product" | "quantity" | "unit_price" | "discount_rate";

type LinesGridProps = {
  /** The grid's name for a screen reader: "Produits". */
  label: string;
  /** The rows, ending with a blank one (`withSpare`). */
  lines: Line[];
  onChange: (lines: Line[]) => void;
  products: Product[];
  /** The price a product is charged until one is typed: the customer's own list, else the daily price. */
  proposedPrice: (product: string) => string | null;
  /** Kilos per product over all the places; missing while the stock is not loaded. The row shows what is left. */
  stock?: Map<string, string>;
  /** The place each product leaves from, once the sale has one (D-144); shown under the product. */
  origin?: Map<string, string>;
  /** The places holding each product, fullest first, with the kilos in each: listed under the product. Missing while the stock is not loaded. */
  places?: Map<string, PlaceKilos[]>;
  /** The partners of each product's lots still being sold (names). Missing while unknown; a product with none shows "Sans partenaire". */
  partners?: Map<string, string[]>;
  /** Messages keyed "lines.<n>.<field>", where n counts the filled rows only, as they are sent. */
  errors: Record<string, string>;
  /** The discount column: a quote and a sale have one, the counter sale does not. */
  discount?: boolean;
  /** The price and amount columns: a transfer that is not a truck load has none (D-174). */
  price?: boolean;
  /** One more column after the product, with its own controls: the counter sale's lot. */
  extra?: {
    header: string;
    /** The field its messages are keyed by. */
    field: string;
    cell: (line: Line, change: (fields: Partial<Line>) => void) => ReactNode;
  };
  /** Said under the grid about the row being typed in: where its price comes from. */
  hint?: (line: Line) => string;
  /** The cursor starts in the first product cell: the counter sale is typed straight away. */
  autoFocus?: boolean;
};

const CELL = "border border-line p-0 align-top";
const CELL_INPUT =
  "block w-full bg-transparent px-2.5 py-2 text-ink outline-none placeholder:text-ink-2/70 focus:bg-sea-soft focus:inset-ring-2 focus:inset-ring-sea aria-invalid:bg-bad-soft";
const CELL_TEXT = "px-2.5 py-2";

/**
 * The rows of a quote, a sale or a counter sale as one grid, typed like a spreadsheet (D-139): click a cell and
 * type, Enter goes to the next cell and then to the next row, the arrows move between cells, and a blank row
 * always waits at the end. The product cell searches by code, name, Arabic name or category.
 */
export function LinesGrid({
  label,
  lines,
  onChange,
  products,
  proposedPrice,
  stock,
  origin,
  places,
  partners,
  errors,
  discount = false,
  price: priced = true,
  extra,
  hint,
  autoFocus = false,
}: LinesGridProps) {
  const { t } = useTranslation();
  const table = useRef<HTMLTableElement>(null);
  // The cell to focus once the rows are drawn again, after a row is removed.
  const wanted = useRef<{ row: number; column: Column } | null>(null);
  const [activeKey, setActiveKey] = useState<number | null>(null);

  const columns: Column[] = !priced
    ? ["product", "quantity"]
    : discount
      ? ["product", "quantity", "unit_price", "discount_rate"]
      : ["product", "quantity", "unit_price"];
  const options = useMemo<ComboboxOption[]>(
    () =>
      products.map((product) => {
        // "En stock : 123,000 kg · Frigo 1 : 100,000 kg · Frigo 2 : 23,000 kg", or "Plus de stock" when none is kept.
        const kept = places?.get(String(product.id));
        const stockText =
          kept && kept.length > 0
            ? [
                t("admin.lines.stockOf", { kg: formatQuantity(sum(kept.map((place) => place.kg))) }),
                ...kept.map((place) =>
                  t("admin.lines.placeKilos", { place: place.place, kg: formatQuantity(place.kg) }),
                ),
              ].join(" · ")
            : t("admin.lines.noStock");
        return {
          value: String(product.id),
          label: `${product.name} · ${product.reference}`,
          keywords: [product.name_ar, product.category.name],
          detail: (
            <span className="flex flex-col gap-0.5">
              <span className="flex items-baseline justify-between gap-4">
                <span>{product.name}</span>
                <span className="num text-[0.8rem] text-ink-2">{product.reference}</span>
              </span>
              {places && <span className="num text-[0.78rem] text-ink-2">{stockText}</span>}
            </span>
          ),
        };
      }),
    [products, places, t],
  );

  function focusCell(row: number, column: Column) {
    table.current?.querySelector<HTMLInputElement>(`[data-row="${row}"][data-column="${column}"]`)?.focus();
  }
  useEffect(() => {
    if (!wanted.current) return;
    focusCell(wanted.current.row, wanted.current.column);
    wanted.current = null;
  });

  const setLine = (key: number, change: Partial<Line>) =>
    onChange(withSpare(lines.map((line) => (line.key === key ? { ...line, ...change } : line))));

  function remove(row: number, column: Column) {
    const left = withSpare(lines.filter((_, index) => index !== row));
    wanted.current = { row: Math.min(row, left.length - 1), column };
    onChange(left);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTableElement>) {
    const cell = event.target;
    if (!(cell instanceof HTMLInputElement) || !cell.dataset.column) return;
    const column = cell.dataset.column as Column;
    const row = Number(cell.dataset.row);
    const at = columns.indexOf(column);
    if (event.key === "Enter") {
      // Never the form's Enter: the next cell, then the first cell of the next row.
      event.preventDefault();
      const next = columns[at + 1];
      if (next) focusCell(row, next);
      else focusCell(row + 1, "product");
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusCell(row + (event.key === "ArrowDown" ? 1 : -1), column);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      // Sideways only from the edge of what is typed (or when all of it is selected), and never while the
      // product list is open: inside the text, the arrows move the cursor.
      if (cell.getAttribute("aria-expanded") === "true") return;
      const { selectionStart, selectionEnd, value } = cell;
      const whole = selectionStart === 0 && selectionEnd === value.length;
      const forward = (event.key === "ArrowRight") !== (getComputedStyle(cell).direction === "rtl");
      if (!whole && (forward ? selectionStart !== value.length : selectionEnd !== 0)) return;
      const next = columns[at + (forward ? 1 : -1)];
      if (!next) return;
      event.preventDefault();
      focusCell(row, next);
    } else if (event.key === "Delete" && event.ctrlKey) {
      event.preventDefault();
      const line = lines[row];
      if (line && !isBlank(line)) remove(row, column);
    }
  }

  // The first click on a cell selects what it holds, so typing replaces it; a click in the cell being typed in
  // places the cursor.
  function onMouseDown(event: MouseEvent<HTMLTableElement>) {
    const cell = event.target;
    if (!(cell instanceof HTMLInputElement) || !cell.dataset.column || document.activeElement === cell) return;
    event.preventDefault();
    cell.focus();
  }

  const active = lines.find((line) => line.key === activeKey);
  // A row's messages are keyed by its place among the filled rows: blank rows are not sent.
  const sentAt = new Map(filled(lines).map((line, index) => [line.key, index]));

  return (
    <div className="flex flex-col gap-2">
      <Table
        ref={table}
        aria-label={label}
        onKeyDown={onKeyDown}
        onMouseDown={onMouseDown}
        onFocus={(event) => {
          const key = (event.target as HTMLElement).closest("tr")?.dataset.key;
          if (key) setActiveKey(Number(key));
        }}
        // The columns have their widths and the product takes the rest: on a narrow screen the grid scrolls
        // sideways before the product gets too small to read.
        className={cn("table-fixed", extra ? "min-w-[62rem]" : priced ? "min-w-[56rem]" : "min-w-[40rem]")}
      >
        <thead>
          <tr className="bg-surface-2">
            <Th className="w-10 border border-line text-center">{t("admin.lines.number")}</Th>
            <Th className="border border-line">{t("admin.lines.product")}</Th>
            {extra && <Th className="w-52 border border-line">{extra.header}</Th>}
            <Th numeric className="w-28 border border-line">
              {t("admin.lines.quantity")}
            </Th>
            {priced && (
              <Th numeric className="w-32 border border-line">
                {t("admin.lines.price")}
              </Th>
            )}
            {discount && (
              <Th numeric className="w-24 border border-line">
                {t("admin.lines.discount")}
              </Th>
            )}
            <Th numeric className="w-32 border border-line">
              {t("admin.lines.remaining")}
            </Th>
            {priced && (
              <Th numeric className="w-36 border border-line">
                {t("admin.lines.amount")}
              </Th>
            )}
            <Th className="w-11 border border-line" />
          </tr>
        </thead>
        <tbody>
          {lines.map((line, row) => {
            const blank = isBlank(line);
            const errorOf = (field: string) => (blank ? undefined : errors[`lines.${sentAt.get(line.key)}.${field}`]);
            const duplicate =
              line.product !== "" && lines.findIndex((other) => other.product === line.product) !== row
                ? t("admin.lines.duplicate")
                : undefined;
            const price = shownPrice(line, line.product ? proposedPrice(line.product) : null);
            const amounts = amountsOf(line, price);
            const available = stock && line.product ? (stock.get(line.product) ?? "0") : undefined;
            // What is left once this row is taken out of the stock; a negative amount is shown in red.
            const typedKg = parseDecimalInput(line.quantity.trim(), 3);
            const left = available !== undefined ? subtract(available, typedKg ?? "0") : undefined;
            // The price after the discount against the product's minimum price (D-163): the server refuses it.
            const minimum = products.find((product) => String(product.id) === line.product)?.min_price ?? null;
            const underMinimum = discount && !blank ? netUnderMinimum(line, price, minimum) : null;
            const message = (text: string | undefined) =>
              text && <p className="px-2.5 pb-1.5 text-[0.78rem] font-semibold text-bad">{text}</p>;
            const number = (
              column: Exclude<Column, "product">,
              name: string,
              value: string,
              under?: string | null | false,
            ) => (
              <td className={CELL}>
                <input
                  data-row={row}
                  data-column={column}
                  aria-label={name}
                  aria-invalid={errorOf(column) ? true : undefined}
                  inputMode="decimal"
                  autoComplete="off"
                  size={1}
                  value={value}
                  onChange={(event) =>
                    setLine(
                      line.key,
                      column === "unit_price"
                        ? { unit_price: event.target.value, priceTouched: true }
                        : { [column]: event.target.value },
                    )
                  }
                  onFocus={(event) => event.currentTarget.select()}
                  className={cn(CELL_INPUT, "num text-end")}
                />
                {message(errorOf(column))}
                {under && !errorOf(column) && (
                  <p className="px-2.5 pb-1.5 text-[0.78rem] font-semibold text-bad">
                    {t("admin.lines.underMinimum", { net: formatMoney(under), minimum: formatMoney(minimum ?? "0") })}
                  </p>
                )}
              </td>
            );
            return (
              <tr key={line.key} data-key={line.key} aria-label={t("admin.lines.row", { number: row + 1 })}>
                <td className={cn(CELL, CELL_TEXT, "num bg-surface-2 text-center text-[0.8rem] text-ink-2")}>
                  {row + 1}
                </td>
                <td className={CELL}>
                  <Combobox
                    plain
                    arrowsOpen={false}
                    data-row={row}
                    data-column="product"
                    aria-label={t("admin.lines.product")}
                    aria-invalid={(errorOf("product") ?? duplicate) ? true : undefined}
                    size={1}
                    autoFocus={autoFocus && row === 0}
                    placeholder={blank ? t("admin.lines.productHint") : undefined}
                    value={line.product}
                    onValueChange={(product) =>
                      setLine(line.key, { product, priceTouched: false, unit_price: "", batch: "" })
                    }
                    onChosen={() => focusCell(row, "quantity")}
                    options={options}
                    empty={t("admin.lines.noProduct")}
                    className={CELL_INPUT}
                  />
                  {message(errorOf("product") ?? duplicate)}
                  {discount && line.product && minimum === null && (
                    <p className="px-2.5 pb-1.5 text-[0.78rem] text-warn">{t("admin.lines.noMinimum")}</p>
                  )}
                  {line.product && (places || partners) && (
                    <div className="flex flex-wrap gap-1 px-2.5 pb-1.5">
                      {places?.get(line.product)?.map((place) => (
                        <Pill key={place.place} tone="sea">
                          {t("admin.lines.placeKilos", { place: place.place, kg: formatQuantity(place.kg) })}
                        </Pill>
                      ))}
                      {partners &&
                        (partners.get(line.product)?.length ? (
                          <Pill tone="coral">
                            {t("admin.lines.partnerWith", { name: partners.get(line.product)?.join(", ") })}
                          </Pill>
                        ) : (
                          <Pill>{t("admin.lines.noPartner")}</Pill>
                        ))}
                    </div>
                  )}
                  {line.product && origin?.get(line.product) && (
                    <p className="px-2.5 pb-1.5 text-[0.78rem] text-ink-2">
                      {t("admin.lines.origin", { place: origin.get(line.product) })}
                    </p>
                  )}
                </td>
                {extra && (
                  <td className={CELL}>
                    {extra.cell(line, (fields) => setLine(line.key, fields))}
                    {message(errorOf(extra.field))}
                  </td>
                )}
                {number("quantity", t("admin.lines.quantity"), line.quantity)}
                {priced &&
                  number("unit_price", t("admin.lines.price"), price, line.discount_rate ? null : underMinimum)}
                {discount && number("discount_rate", t("admin.lines.discount"), line.discount_rate, underMinimum)}
                <td
                  className={cn(
                    CELL,
                    CELL_TEXT,
                    "num text-end text-ink-2",
                    left !== undefined &&
                      (left.startsWith("-") || isShort(line.quantity, available)) &&
                      "font-semibold text-bad",
                  )}
                >
                  {left !== undefined ? formatQuantity(left) : line.product ? "—" : ""}
                </td>
                {priced && (
                  <td className={cn(CELL, CELL_TEXT, "num text-end font-semibold")}>
                    {amounts ? formatMoney(amounts.amount) : ""}
                  </td>
                )}
                <td className={cn(CELL, "text-center align-middle")}>
                  {!blank && (
                    // Out of the Tab order, so Tab goes from cell to cell: Ctrl + Delete removes a row from the keyboard.
                    <Button
                      size="icon"
                      variant="ghost"
                      tabIndex={-1}
                      aria-label={t("admin.lines.remove", { number: row + 1 })}
                      title={t("admin.lines.remove", { number: row + 1 })}
                      onClick={() => remove(row, "product")}
                    >
                      <Icon name="trash" />
                    </Button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </Table>
      <div className="flex flex-wrap justify-between gap-x-6 gap-y-1 text-[0.8rem] text-ink-2">
        <p aria-live="polite">{active?.product && hint ? hint(active) : ""}</p>
        <p>{t("admin.lines.keys")}</p>
      </div>
    </div>
  );
}
