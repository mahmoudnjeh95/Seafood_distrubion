// ESC/POS bytes, the command set nearly every small thermal printer understands.
import type { Row } from "./receipt";

const ESC = 0x1b;
const GS = 0x1d;

// Code page 858 (Western Europe with the euro sign): the accents French needs, one byte each.
const CP858: Record<string, number> = {
  Ç: 0x80,
  ü: 0x81,
  é: 0x82,
  â: 0x83,
  ä: 0x84,
  à: 0x85,
  ç: 0x87,
  ê: 0x88,
  ë: 0x89,
  è: 0x8a,
  ï: 0x8b,
  î: 0x8c,
  É: 0x90,
  ô: 0x93,
  ö: 0x94,
  û: 0x96,
  ù: 0x97,
  ÿ: 0x98,
  Ü: 0x9a,
  "€": 0xd5,
  "°": 0xf8,
  À: 0xb7,
  Â: 0xb6,
  Ê: 0xd2,
  È: 0xd4,
  Î: 0xd7,
  Ô: 0xe2,
  Û: 0xea,
  Ù: 0xeb,
};
const MARKS = /[\u0300-\u036f]/g;

/** Text to bytes. With `accents` off (a printer that shows garbage for code page 858) the accents are dropped. */
export function encodeText(text: string, accents: boolean): number[] {
  const out: number[] = [];
  for (const char of text.replace(/[\u00a0\u202f\u2009]/g, " ")) {
    const code = char.codePointAt(0) ?? 0x3f;
    if (code < 0x80) out.push(code);
    else if (accents && CP858[char] !== undefined) out.push(CP858[char]);
    else {
      const plain = char.normalize("NFD").replace(MARKS, "");
      out.push(plain.length === 1 && plain.charCodeAt(0) < 0x80 ? plain.charCodeAt(0) : 0x3f);
    }
  }
  return out;
}

export type EscposOptions = { cols: number; accents: boolean };

/** One print job: the rows of every copy, with a paper cut after each one (printers without a cutter ignore it). */
export function escposJob(copies: Row[][], { cols, accents }: EscposOptions): Uint8Array {
  const bytes: number[] = [ESC, 0x40]; // reset
  if (accents) bytes.push(ESC, 0x74, 19); // code page 858
  for (const rows of copies) {
    for (const row of rows) {
      // No logo and no Arabic in the text mode: the printer's own characters have neither (D-282).
      if ("logo" in row || ("ar" in row && row.ar)) continue;
      if ("feed" in row) {
        bytes.push(ESC, 0x64, row.feed);
      } else if ("rule" in row) {
        bytes.push(ESC, 0x61, 0, ...encodeText(row.rule.repeat(cols), accents), 0x0a);
      } else {
        const align = row.align === "center" ? 1 : row.align === "right" ? 2 : 0;
        // Double height only: the line keeps its width, so the right-hand column stays on the paper.
        bytes.push(ESC, 0x61, align, ESC, 0x45, row.bold ? 1 : 0, GS, 0x21, row.big ? 0x01 : 0x00);
        bytes.push(...encodeText(row.text, accents), 0x0a, GS, 0x21, 0x00, ESC, 0x45, 0x00);
      }
    }
    bytes.push(GS, 0x56, 0x42, 0x00); // feed and cut
  }
  return Uint8Array.from(bytes);
}

/** A black and white picture, one bit per dot (1 = black), `width` dots wide (a multiple of 8). */
export type Bitmap = { width: number; height: number; bits: Uint8Array };

// A band of at most this many dot rows per command: small printers have small buffers.
const BAND = 128;

/** One print job of pictures (D-282): each copy is printed as dots (GS v 0), then fed and cut. */
export function rasterJob(copies: Bitmap[]): Uint8Array {
  const bytes: number[] = [ESC, 0x40];
  for (const { width, height, bits } of copies) {
    const rowBytes = width / 8;
    for (let top = 0; top < height; top += BAND) {
      const rows = Math.min(BAND, height - top);
      bytes.push(GS, 0x76, 0x30, 0, rowBytes & 0xff, rowBytes >> 8, rows & 0xff, rows >> 8);
      for (let at = top * rowBytes; at < (top + rows) * rowBytes; at += 1) bytes.push(bits[at] ?? 0);
    }
    bytes.push(ESC, 0x64, 3, GS, 0x56, 0x42, 0x00);
  }
  return Uint8Array.from(bytes);
}

/** RGBA pixels (a canvas) to one bit per dot: dark enough is black. */
export function toBits(rgba: Uint8ClampedArray, width: number, height: number): Bitmap {
  const rowBytes = width / 8;
  const bits = new Uint8Array(rowBytes * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const at = (y * width + x) * 4;
      const alpha = (rgba[at + 3] ?? 0) / 255;
      // Transparent counts as white paper.
      const light =
        255 - alpha * (255 - ((rgba[at] ?? 0) * 0.299 + (rgba[at + 1] ?? 0) * 0.587 + (rgba[at + 2] ?? 0) * 0.114));
      if (light < 128) {
        const index = y * rowBytes + (x >> 3);
        bits[index] = (bits[index] ?? 0) | (0x80 >> (x & 7));
      }
    }
  }
  return { width, height, bits };
}
