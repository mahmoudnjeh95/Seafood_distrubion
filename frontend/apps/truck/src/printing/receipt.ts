// Receipt layout for a small thermal printer. Pure functions: a receipt becomes rows of text, the rows become
// either a plain-text preview or ESC/POS bytes (escpos.ts). Receipts are always in French (Q13), whatever
// language the driver uses in the app, and every number is written the way the paper invoices do: "1 250,000".

export type ReceiptKind = "sale" | "purchase";
/** Who keeps this paper: the customer or supplier, or the office (with a line for the signature). */
export type ReceiptCopy = "party" | "office";

/** `unitPrice` is left out when only the kilos and the amount are known (a sale still kept on the phone). */
export type ReceiptLine = { name: string; quantity: string; unitPrice?: string; amount: string };

/** The number printed on a receipt the office has not received yet: it gets its real number when it is sent. */
export const PROVISIONAL = "Provisoire";
/** The line printed under the totals of such a receipt. */
export const PROVISIONAL_NOTE = "Pas encore envoyé au bureau : le numéro sera donné à l'envoi.";

export type ReceiptData = {
  kind: ReceiptKind;
  company: string;
  number: string;
  /** ISO date or timestamp. */
  date: string;
  partyName: string;
  lines: ReceiptLine[];
  total: string;
  paid: string;
  rest: string;
  /** The driver's name, printed under the date. */
  by?: string;
  /** A line of text under the totals. */
  note?: string;
};

export type Align = "left" | "center" | "right";
export type Row =
  { text: string; align?: Align; bold?: boolean; big?: boolean } | { rule: "-" | "=" } | { feed: number };

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

function frenchDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const parts = new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Africa/Tunis",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(date);
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("day")}/${part("month")}/${part("year")} ${part("hour")}:${part("minute")}`;
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

export function layoutReceipt(data: ReceiptData, copy: ReceiptCopy, cols: number): Row[] {
  const { title, party } = TITLES[data.kind];
  const rows: Row[] = [];
  if (data.company !== "") rows.push({ text: data.company, align: "center", bold: true, big: true });
  rows.push({ text: title, align: "center", bold: true });
  rows.push({ rule: "=" });
  rows.push({ text: twoColumns("N°", data.number, cols) });
  rows.push({ text: twoColumns("Date", frenchDate(data.date), cols) });
  if (data.by) rows.push({ text: twoColumns("Chauffeur", data.by, cols) });
  const names = wrap(data.partyName, cols - party.length - 2);
  rows.push({ text: twoColumns(party, names[0] ?? "", cols) });
  for (const text of names.slice(1)) rows.push({ text, align: "right" });
  rows.push({ rule: "-" });
  for (const line of data.lines) {
    for (const text of wrap(line.name, cols)) rows.push({ text, bold: true });
    const each = line.unitPrice === undefined ? "" : ` x ${amount(line.unitPrice)}`;
    rows.push({ text: twoColumns(`  ${kilos(line.quantity)}${each}`, amount(line.amount), cols) });
  }
  rows.push({ rule: "-" });
  rows.push({ text: twoColumns("TOTAL DT", amount(data.total), cols), bold: true });
  rows.push({ text: twoColumns("Payé", amount(data.paid), cols) });
  if (Number(data.rest) > 0) rows.push({ text: twoColumns("Reste à payer", amount(data.rest), cols), bold: true });
  if (data.note) for (const text of wrap(data.note, cols)) rows.push({ text });
  rows.push({ rule: "-" });
  if (copy === "office") {
    rows.push({ text: "COPIE BUREAU", align: "center", bold: true });
    rows.push({ feed: 2 });
    rows.push({ text: `Signature ${party.toLowerCase()} :` });
    rows.push({ feed: 3 });
  } else {
    rows.push({ text: "Merci de votre confiance", align: "center" });
  }
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
    .map((row) => {
      if ("rule" in row) return row.rule.repeat(cols);
      if ("feed" in row) return "\n".repeat(row.feed - 1);
      return placed(row.text, row.align ?? "left", cols);
    })
    .join("\n");
}
