// The état of the invoices as a CSV file that Excel opens (P9-T08): `;` between cells, French decimal commas, a
// byte-order mark so the accents survive.

/** The file's text: one line per row, every cell quoted when it holds a `;`, a quote or a line break. */
export function csvFile(rows: readonly (readonly string[])[]): string {
  const body = rows.map((row) => row.map(cell).join(";")).join("\r\n");
  return `﻿${body}\r\n`;
}

function cell(value: string): string {
  return /[";\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

/** A money amount as a French spreadsheet reads it: "1200.500" → "1200,500". */
export function csvMoney(amount: string): string {
  return amount.replace(".", ",");
}

/** Saves the text as a file the browser downloads. */
export function downloadCsv(name: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
