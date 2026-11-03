// Receipt layout for a small thermal printer. Pure functions: a receipt becomes rows of text, the rows become
// either a plain-text preview, ESC/POS text bytes (escpos.ts) or a picture (raster.ts). Receipts are in French
// (Q13), whatever language the driver uses in the app; only the product names also come in Arabic (D-282). Every
// number is written the way the paper invoices do: "1 250,000".

export type ReceiptKind = "sale" | "purchase";
/** Who keeps this paper: the customer or supplier, or the office (with a line for the signature). */
export type ReceiptCopy = "party" | "office";

/** `unitPrice` is left out when only the kilos and the amount are known (a sale still kept on the phone).
 * `nameAr`: the product's Arabic name, printed under the French one when the product has one (D-282). */
export type ReceiptLine = { name: string; nameAr?: string; quantity: string; unitPrice?: string; amount: string };

/** The number printed on a receipt the office has not received yet: it gets its real number when it is sent. */
export const PROVISIONAL = "Provisoire";
/** The line printed under the totals of such a receipt. */
export const PROVISIONAL_NOTE = "Pas encore envoyé au bureau : le numéro sera donné à l'envoi.";

/** The seller at the top of the paper (D-281): the finance settings' legal name, address, phone and matricule fiscal. */
export type ReceiptSeller = { name: string; address?: string; phone?: string; taxId?: string };

export type ReceiptData = {
  kind: ReceiptKind;
  company: string;
  /** The seller's address, phone and matricule fiscal, printed under the name when known. */
  seller?: Omit<ReceiptSeller, "name">;
  number: string;
  /** ISO date or timestamp. */
  date: string;
  partyName: string;
  lines: ReceiptLine[];
  total: string;
  paid: string;
  rest: string;
  /** The driver's name, printed at the bottom ("Préparé par"). */
  by?: string;
  /** A line of text under the totals. */
  note?: string;
};

export type Align = "left" | "center" | "right";
/** `ar`: Arabic text, drawn right to left; only a picture prints it (the text mode leaves the row out, D-282).
 * `logo`: the company logo, at the top of a printed picture (nothing in the text mode). */
export type Row =
  | { text: string; align?: Align; bold?: boolean; big?: boolean; ar?: boolean }
  | { rule: "-" | "=" }
  | { feed: number }
  | { logo: true };

/** Characters per line for the usual paper widths: 58 mm = 32, 75 to 76 mm = 42, 80 mm = 48. */
export const WIDTHS = [32, 42, 48] as const;
export const DEFAULT_WIDTH = 32;

const GROUP = /\B(?=(\d{3})+(?!\d))/g;

/** "1250" → "1 250,000": any decimal string, kept at 3 places. */
export function amount(value: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  const [whole = "0", decimals = "000"] = Math.abs(n).toFixed(3).split(".");
  return `${n < 0 ? "-" : ""}${whole.replace(GROUP, " ")},${decimals}`;
}

const kilos = (value: string) => `${amount(value)} kg`;

/** "02/11/2026" and "10:41", in Tunis time. */
function frenchDate(iso: string): { day: string; time: string } {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return { day: iso, time: "" };
  const parts = new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Africa/Tunis",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(date);
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return { day: `${part("day")}/${part("month")}/${part("year")}`, time: `${part("hour")}:${part("minute")}` };
}

/** Left text and right text on one line; the left one is cut if the two do not fit. */
export function twoColumns(left: string, right: string, cols: number): string {
  const room = Math.max(cols - right.length - 1, 0);
  const cut = left.length > room ? left.slice(0, room) : left;
  return cut + " ".repeat(Math.max(cols - cut.length - right.length, 1)) + right;
}

/** Cuts a long text into lines of at most `cols` characters, on spaces where possible. */
export function wrap(text: string, cols: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    let rest = word;
    while (rest.length > cols) {
      if (line !== "") {
        out.push(line);
        line = "";
      }
      out.push(rest.slice(0, cols));
      rest = rest.slice(cols);
    }
    if (line === "") line = rest;
    else if (line.length + 1 + rest.length <= cols) line += ` ${rest}`;
    else {
      out.push(line);
      line = rest;
    }
  }
  if (line !== "") out.push(line);
  return out;
}

const TITLES: Record<ReceiptKind, { title: string; party: string }> = {
  sale: { title: "REÇU DE VENTE", party: "Client" },
  purchase: { title: "REÇU D'ACHAT", party: "Fournisseur" },
};

// The three number columns of the goods table, right-aligned: kilos, price per kg, amount. Together 32 characters,
// the 58 mm paper; on wider paper the product name has room on the same line.
const QTY = 10;
const PRICE = 10;
const AMOUNT = 12;
const NUMBERS = QTY + PRICE + AMOUNT;
// Below this many characters left for the name, the name has its own line above its numbers.
const NAME_ROOM = 12;

const numbers = (qty: string, price: string, total: string) =>
  qty.padStart(QTY) + price.padStart(PRICE) + total.padStart(AMOUNT);

function goodsTable(lines: ReceiptLine[], cols: number): Row[] {
  const room = cols - NUMBERS;
  const wide = room >= NAME_ROOM;
  const rows: Row[] = [];
  const head = numbers("Qté kg", "Prix", "Montant");
  if (wide) rows.push({ text: "Article".padEnd(room) + head, bold: true });
  else rows.push({ text: "Article", bold: true }, { text: head, align: "right", bold: true });
  rows.push({ rule: "-" });
  for (const line of lines) {
    const values = numbers(
      amount(line.quantity),
      line.unitPrice === undefined ? "" : amount(line.unitPrice),
      amount(line.amount),
    );
    // A very large number does not fit the columns: kilos and price on one line, the amount on the next.
    const arabic: Row[] = line.nameAr ? [{ text: line.nameAr, align: wide ? "left" : "right", ar: true }] : [];
    if (values.length > cols) {
      for (const text of wrap(line.name, cols)) rows.push({ text, bold: true });
      rows.push(...arabic);
      const each = line.unitPrice === undefined ? "" : ` x ${amount(line.unitPrice)}`;
      rows.push({ text: `  ${kilos(line.quantity)}${each}` }, { text: amount(line.amount), align: "right" });
      continue;
    }
    if (wide) {
      const names = wrap(line.name, room - 1);
      rows.push({ text: (names[0] ?? "").padEnd(room) + values });
      for (const text of names.slice(1)) rows.push({ text });
      rows.push(...arabic);
    } else {
      for (const text of wrap(line.name, cols)) rows.push({ text, bold: true });
      rows.push(...arabic);
      rows.push({ text: values, align: "right" });
    }
  }
  return rows;
}

/** Who keeps this paper, printed big at the top of the office copy so the two papers are never mixed up. */
export const COPY_TITLES: Record<ReceiptCopy, string> = { party: "", office: "COPIE BUREAU" };

export function layoutReceipt(data: ReceiptData, copy: ReceiptCopy, cols: number): Row[] {
  const { title, party } = TITLES[data.kind];
  // The logo heads a printed picture; the text mode and the preview text leave it out.
  const rows: Row[] = [{ logo: true }];
  if (data.company !== "") {
    for (const text of wrap(data.company, cols)) rows.push({ text, align: "center", bold: true, big: true });
  }
  const seller = data.seller ?? {};
  if (seller.address) for (const text of wrap(seller.address, cols)) rows.push({ text, align: "center" });
  if (seller.phone) rows.push({ text: `Tél : ${seller.phone}`, align: "center" });
  if (seller.taxId) rows.push({ text: `MF : ${seller.taxId}`, align: "center" });
  rows.push({ rule: "=" });
  rows.push({ text: title, align: "center", bold: true });
  if (copy === "office") rows.push({ text: `** ${COPY_TITLES.office} **`, align: "center", bold: true });
  rows.push({ rule: "-" });
  const when = frenchDate(data.date);
  rows.push({ text: twoColumns("N°", data.number, cols) });
  rows.push({ text: twoColumns("Date", when.day, cols) });
  if (when.time !== "") rows.push({ text: twoColumns("Heure", when.time, cols) });
  const names = wrap(data.partyName, cols - party.length - 2);
  rows.push({ text: twoColumns(party, names[0] ?? "", cols) });
  for (const text of names.slice(1)) rows.push({ text, align: "right" });
  rows.push({ rule: "-" });
  rows.push(...goodsTable(data.lines, cols));
  rows.push({ rule: "-" });
  rows.push({ text: twoColumns("TOTAL DT", amount(data.total), cols), bold: true, big: true });
  rows.push({ text: twoColumns("Payé", amount(data.paid), cols) });
  if (Number(data.rest) > 0) rows.push({ text: twoColumns("Reste à payer", amount(data.rest), cols), bold: true });
  if (data.note) for (const text of wrap(data.note, cols)) rows.push({ text });
  rows.push({ rule: "-" });
  if (copy === "office") {
    rows.push({ feed: 2 });
    rows.push({ text: `Signature ${party.toLowerCase()} :` });
    rows.push({ feed: 3 });
  } else {
    rows.push({ text: "Merci de votre confiance", align: "center" });
  }
  if (data.by) for (const text of wrap(`Préparé par : ${data.by}`, cols)) rows.push({ text, align: "center" });
  rows.push({ feed: 3 });
  return rows;
}

function placed(text: string, align: Align, cols: number): string {
  if (align === "center") return " ".repeat(Math.max(Math.floor((cols - text.length) / 2), 0)) + text;
  if (align === "right") return " ".repeat(Math.max(cols - text.length, 0)) + text;
  return text;
}

/** The receipt as plain text, the way it comes out of the printer (the on-screen preview and the tests). */
export function previewText(rows: Row[], cols: number): string {
  return rows
    .flatMap((row) => {
      if ("logo" in row) return [];
      if ("rule" in row) return [row.rule.repeat(cols)];
      if ("feed" in row) return ["\n".repeat(row.feed - 1)];
      return [placed(row.text, row.align ?? "left", cols)];
    })
    .join("\n");
}
