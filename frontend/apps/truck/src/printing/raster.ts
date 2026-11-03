// The receipt drawn as a picture (D-282): the phone draws the rows on a canvas, which writes Arabic right to left
// with its joined letters and puts the company logo at the top, and the printer prints the dots. The printer's own
// characters have neither Arabic nor pictures, so this is the default; the text mode stays for a printer that
// cannot print pictures.
import { type Bitmap, toBits } from "./escpos";
import type { Row, Size } from "./receipt";

/** Dots per line of the usual papers at 203 dpi: 58 mm prints 48 mm (384 dots), 80 mm prints 72 mm (576). */
export const DOTS: Record<number, number> = { 32: 384, 42: 512, 48: 576 };

const SANS = "Roboto, 'Noto Sans', 'DejaVu Sans', Arial, sans-serif";
const ARABIC = "'Noto Naskh Arabic', 'Noto Sans Arabic', Tahoma, sans-serif";
// The logo, cut to its ink, is at most this share of the paper's width and this many dots high (about 2 cm at
// 203 dpi). Smaller than the paper: the printer faded and cut a logo as wide as the paper at its left edge.
const LOGO_WIDTH = 0.8;
const LOGO_HEIGHT = 170;

function loadImage(source: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = source;
  });
}

/** The grey level that best splits the picture in two (Otsu): the logo's ink on one side, the paper on the other. */
export function splitLevel(grey: ArrayLike<number>): number {
  const counts = new Array<number>(256).fill(0);
  for (let i = 0; i < grey.length; i += 1) {
    const level = Math.round(grey[i] ?? 0);
    counts[level] = (counts[level] ?? 0) + 1;
  }
  const total = grey.length;
  let sum = 0;
  for (let level = 0; level < 256; level += 1) sum += level * (counts[level] ?? 0);
  let below = 0;
  let belowSum = 0;
  let best = 128;
  let bestSpread = -1;
  for (let level = 0; level < 256; level += 1) {
    below += counts[level] ?? 0;
    if (below === 0) continue;
    const above = total - below;
    if (above === 0) break;
    belowSum += level * (counts[level] ?? 0);
    const spread = below * above * (belowSum / below - (sum - belowSum) / above) ** 2;
    if (spread > bestSpread) {
      bestSpread = spread;
      best = level;
    }
  }
  return best;
}

type Grey = { grey: Float32Array; width: number; height: number };

/** The picture flattened on white paper, as grey levels, `width` × `height` dots (from the `source` part of it). */
function greyOf(
  image: HTMLImageElement,
  width: number,
  height: number,
  source = { x: 0, y: 0, width: image.width, height: image.height },
): Grey | null {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (context === null) return null;
  context.fillStyle = "#fff";
  context.fillRect(0, 0, width, height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(image, source.x, source.y, source.width, source.height, 0, 0, width, height);
  const data = context.getImageData(0, 0, width, height).data;
  const grey = new Float32Array(width * height);
  for (let i = 0; i < grey.length; i += 1) {
    grey[i] = (data[i * 4] ?? 0) * 0.299 + (data[i * 4 + 1] ?? 0) * 0.587 + (data[i * 4 + 2] ?? 0) * 0.114;
  }
  return { grey, width, height };
}

/** Whether the border is mostly at or below `level`: a light logo on a dark ground, to be turned over. */
function darkGround({ grey, width, height }: Grey, level: number): boolean {
  let border = 0;
  let dark = 0;
  const look = (x: number, y: number) => {
    border += 1;
    if ((grey[y * width + x] ?? 255) <= level) dark += 1;
  };
  for (let x = 0; x < width; x += 1) {
    look(x, 0);
    look(x, height - 1);
  }
  for (let y = 0; y < height; y += 1) {
    look(0, y);
    look(width - 1, y);
  }
  return dark > border / 2;
}

/** The smallest box around the ink, so white margins in the file do not shrink the printed logo. */
function inkBox({ grey, width, height }: Grey, level: number, turnOver: boolean) {
  let left = width;
  let right = -1;
  let top = height;
  let bottom = -1;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if ((grey[y * width + x] ?? 255) <= level === turnOver) continue;
      left = Math.min(left, x);
      right = Math.max(right, x);
      top = Math.min(top, y);
      bottom = Math.max(bottom, y);
    }
  }
  if (right < 0) return { x: 0, y: 0, width, height };
  return { x: left, y: top, width: right - left + 1, height: bottom - top + 1 };
}

/**
 * The logo in black and white dots (D-282): flattened on white paper, cut to its ink (no white margins), as wide as
 * the paper allows, then each dot black or white at the level that best splits ink from paper (Otsu), so a coloured
 * logo prints in clean shapes, not a grainy pattern. A logo on a dark background is turned over, so it prints as ink
 * on white paper, not a black block.
 */
function logoDots(image: HTMLImageElement, paper: number): HTMLCanvasElement | null {
  const whole = greyOf(image, image.width, image.height);
  if (whole === null) return null;
  const level = splitLevel(whole.grey);
  const turnOver = darkGround(whole, level);
  const box = turnOver ? { x: 0, y: 0, width: image.width, height: image.height } : inkBox(whole, level, turnOver);
  const scale = Math.min((paper * LOGO_WIDTH) / box.width, LOGO_HEIGHT / box.height, 3);
  const width = Math.max(Math.round(box.width * scale), 1);
  const height = Math.max(Math.round(box.height * scale), 1);
  const small = greyOf(image, width, height, box);
  if (small === null) return null;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (context === null) return null;
  const pixels = context.createImageData(width, height);
  for (let i = 0; i < small.grey.length; i += 1) {
    // Shrinking greys the thin strokes: a dot is ink a little above the split level, so they stay on the paper.
    const ink = (small.grey[i] ?? 255) <= Math.min(level + 40, 230) !== turnOver;
    const value = ink ? 0 : 255;
    pixels.data.set([value, value, value, 255], i * 4);
  }
  context.putImageData(pixels, 0, 0);
  return canvas;
}

/** Draws the rows of one copy on a canvas as wide as the paper's dots (D-282). The picture uses a proportional font
 * and places each label and value by dots, so the columns line up whatever the letters; `cols` sets the size. */
export async function drawReceipt(rows: Row[], cols: number, logo: string | null): Promise<HTMLCanvasElement> {
  const width = DOTS[cols] ?? 384;
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (context === null) throw new Error("canvas");
  // 24 dots on 58 mm paper (the size of the printer's own letters), a little more on wider paper.
  const base = Math.round(16 + width / 48);
  const sizes: Record<Size, number> = {
    small: Math.round(base * 0.85),
    normal: base,
    large: Math.round(base * 1.35),
  };
  const image = logo ? await loadImage(logo) : null;
  const picture = image ? logoDots(image, width) : null;

  // Under a logo the company name is drawn at the normal size: the logo already says it.
  const sizeOf = (row: Row): number => {
    if (!("text" in row || "left" in row)) return base;
    if ("text" in row && row.ar) return Math.round(base * 1.1);
    if ("text" in row && row.company && picture) return base;
    return sizes[row.size ?? "normal"];
  };
  const lineOf = (row: Row) => Math.round(sizeOf(row) * 1.3);
  const heightOf = (row: Row) => {
    if ("logo" in row) return picture ? picture.height + Math.round(base / 2) : 0;
    if ("feed" in row) return row.feed * Math.round(base * 1.3);
    if ("gap" in row) return Math.round(base / 3);
    if ("rule" in row) return Math.round(base * 0.9);
    return lineOf(row);
  };
  canvas.width = width;
  canvas.height = Math.max(
    rows.reduce((sum, row) => sum + heightOf(row), 0),
    1,
  );
  context.fillStyle = "#fff";
  context.fillRect(0, 0, width, canvas.height);
  context.fillStyle = "#000";
  context.textBaseline = "middle";
  context.textAlign = "left";

  /** Draws `text` with its left edge at x, narrowed to `room` dots when longer. */
  const put = (text: string, x: number, middle: number, room: number) => {
    const measured = context.measureText(text).width;
    const squeeze = measured > room ? room / measured : 1;
    context.save();
    context.translate(x, middle);
    context.scale(squeeze, 1);
    context.fillText(text, 0, 0);
    context.restore();
    return Math.min(measured, room);
  };

  let top = 0;
  for (const row of rows) {
    const height = heightOf(row);
    const middle = top + height / 2;
    if ("logo" in row) {
      if (picture) context.drawImage(picture, Math.round((width - picture.width) / 2), top);
    } else if ("rule" in row) {
      if (row.rule === "=") {
        context.fillRect(0, Math.round(middle) - 3, width, 2);
        context.fillRect(0, Math.round(middle) + 1, width, 2);
      } else {
        // A dashed line, lighter on the paper than a full one.
        for (let x = 0; x < width; x += 8) context.fillRect(x, Math.round(middle) - 1, 5, 2);
      }
    } else if ("left" in row) {
      const size = sizeOf(row);
      context.direction = "ltr";
      context.font = `${row.bold || row.strong ? "bold " : ""}${size}px ${SANS}`;
      const right = Math.min(context.measureText(row.right).width, width * 0.7);
      put(row.right, width - right, middle, right);
      context.font = `${row.bold ? "bold " : ""}${size}px ${SANS}`;
      put(row.left, 0, middle, Math.max(width - right - base / 2, base));
    } else if ("text" in row) {
      context.direction = row.ar ? "rtl" : "ltr";
      context.font = `${row.bold || row.ar ? "bold " : ""}${sizeOf(row)}px ${row.ar ? ARABIC : SANS}`;
      const measured = Math.min(context.measureText(row.text).width, width);
      const align = row.align ?? "left";
      const x = align === "center" ? (width - measured) / 2 : align === "right" ? width - measured : 0;
      // "left" puts the text's left edge at x, also right-to-left text, which the canvas joins and orders itself.
      put(row.text, x, middle, width);
    }
    top += height;
  }
  return canvas;
}

/** The copy as one bit per dot, ready for `rasterJob`. */
export async function receiptBitmap(rows: Row[], cols: number, logo: string | null): Promise<Bitmap> {
  const canvas = await drawReceipt(rows, cols, logo);
  const context = canvas.getContext("2d");
  if (context === null) throw new Error("canvas");
  return toBits(context.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height);
}
