// The receipt drawn as a picture (D-282): the phone draws the rows on a canvas, which writes Arabic right to left
// with its joined letters and puts the company logo at the top, and the printer prints the dots. The printer's own
// characters have neither Arabic nor pictures, so this is the default; the text mode stays for a printer that
// cannot print pictures.
import { type Bitmap, toBits } from "./escpos";
import type { Row } from "./receipt";

/** Dots per line of the usual papers at 203 dpi: 58 mm prints 48 mm (384 dots), 80 mm prints 72 mm (576). */
export const DOTS: Record<number, number> = { 32: 384, 42: 512, 48: 576 };

const MONO = "'DejaVu Sans Mono', 'Noto Sans Mono', 'Roboto Mono', monospace";
const ARABIC = "'Noto Naskh Arabic', 'Noto Sans Arabic', Tahoma, sans-serif";
// The logo is at most this share of the paper's width and this many dots high.
const LOGO_WIDTH = 0.6;
const LOGO_HEIGHT = 140;

function loadImage(source: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = source;
  });
}

/** The logo in black dots: grey shades become a dot pattern (Floyd–Steinberg), so a photo-like logo stays readable. */
function ditheredLogo(image: HTMLImageElement, paper: number): HTMLCanvasElement | null {
  const scale = Math.min((paper * LOGO_WIDTH) / image.width, LOGO_HEIGHT / image.height, 1);
  const width = Math.max(Math.round(image.width * scale), 1);
  const height = Math.max(Math.round(image.height * scale), 1);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (context === null) return null;
  context.fillStyle = "#fff";
  context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0, width, height);
  const pixels = context.getImageData(0, 0, width, height);
  const data = pixels.data;
  const grey = new Float32Array(width * height);
  for (let i = 0; i < grey.length; i += 1) {
    grey[i] = (data[i * 4] ?? 0) * 0.299 + (data[i * 4 + 1] ?? 0) * 0.587 + (data[i * 4 + 2] ?? 0) * 0.114;
  }
  const spread = (x: number, y: number, error: number) => {
    if (x < 0 || x >= width || y >= height) return;
    grey[y * width + x] = (grey[y * width + x] ?? 0) + error;
  };
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const old = grey[y * width + x] ?? 0;
      const value = old < 128 ? 0 : 255;
      const error = old - value;
      spread(x + 1, y, (error * 7) / 16);
      spread(x - 1, y + 1, (error * 3) / 16);
      spread(x, y + 1, (error * 5) / 16);
      spread(x + 1, y + 1, error / 16);
      const at = (y * width + x) * 4;
      data[at] = value;
      data[at + 1] = value;
      data[at + 2] = value;
      data[at + 3] = 255;
    }
  }
  context.putImageData(pixels, 0, 0);
  return canvas;
}

/** Draws the rows of one copy, `cols` characters wide, on a canvas as wide as the paper's dots. */
export async function drawReceipt(rows: Row[], cols: number, logo: string | null): Promise<HTMLCanvasElement> {
  const width = DOTS[cols] ?? 384;
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (context === null) throw new Error("canvas");
  // The French rows are laid out in characters: the font is sized so `cols` of them fill the paper.
  context.font = `100px ${MONO}`;
  const size = (width / cols / context.measureText("0").width) * 100;
  const line = Math.round(size * 1.2);
  const image = logo ? await loadImage(logo) : null;
  const picture = image ? ditheredLogo(image, width) : null;

  const heightOf = (row: Row) => {
    if ("logo" in row) return picture ? picture.height + Math.round(line / 2) : 0;
    if ("feed" in row) return row.feed * line;
    if ("rule" in row) return line;
    if (row.ar) return Math.round(line * 1.3);
    return row.big ? line * 2 : line;
  };
  canvas.width = width;
  canvas.height = Math.max(
    rows.reduce((sum, row) => sum + heightOf(row), 0),
    1,
  );
  context.fillStyle = "#fff";
  context.fillRect(0, 0, width, canvas.height);
  context.fillStyle = "#000";
  context.textBaseline = "top";

  let top = 0;
  for (const row of rows) {
    const height = heightOf(row);
    if ("logo" in row) {
      if (picture) context.drawImage(picture, Math.round((width - picture.width) / 2), top);
    } else if ("rule" in row) {
      const middle = top + Math.round(line / 2);
      context.fillRect(0, middle - 1, width, 2);
      if (row.rule === "=") context.fillRect(0, middle + 3, width, 2);
    } else if ("text" in row) {
      const fontSize = row.ar ? Math.round(size * 1.15) : size;
      context.direction = row.ar ? "rtl" : "ltr";
      context.textAlign = "left";
      context.font = `${row.bold || row.ar ? "bold " : ""}${fontSize}px ${row.ar ? ARABIC : MONO}`;
      const text = row.ar ? row.text : row.text.replace(/\s+$/, "");
      let measured = context.measureText(text).width;
      // An Arabic name longer than the paper is drawn narrower rather than cut.
      const squeeze = measured > width ? width / measured : 1;
      measured = Math.min(measured, width);
      const align = row.align ?? "left";
      const x = align === "center" ? (width - measured) / 2 : align === "right" ? width - measured : 0;
      context.save();
      // "left" puts the text's left edge at x, also right-to-left text, which the canvas joins and orders itself.
      context.translate(x, top);
      context.scale(squeeze, row.big ? 2 : 1);
      context.fillText(text, 0, 0);
      context.restore();
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
