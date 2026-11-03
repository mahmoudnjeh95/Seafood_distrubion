// The printer connection (Web Bluetooth, Bluetooth Low Energy) and the printer settings kept on the phone.
// Chrome on Android can do this by itself. Safari on iPhone cannot, so there the buttons say so (printing from
// an iPhone needs the app wrapped as a native app, P3-T10).
import { rememberedLogo } from "../companyLogo";
import { escposJob, rasterJob } from "./escpos";
import { receiptBitmap } from "./raster";
import { DEFAULT_WIDTH, type ReceiptCopy, type ReceiptData, layoutReceipt, type Row, WIDTHS } from "./receipt";

export type PrinterSettings = {
  /** Characters per line: 32 = 58 mm paper, 42 = 75 mm, 48 = 80 mm. */
  cols: number;
  /** Send the French accents (code page 858). Off for a printer that prints garbage. Text mode only. */
  accents: boolean;
  /** Print the receipt as a picture, with the logo and the Arabic product names (D-282). Off: the printer's own
   * text, for a printer that cannot print pictures (no logo, no Arabic). */
  picture: boolean;
};

const KEY = "frutti.printer";
const DEFAULTS: PrinterSettings = { cols: DEFAULT_WIDTH, accents: true, picture: true };

export function loadSettings(): PrinterSettings {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<PrinterSettings>;
    return {
      cols: WIDTHS.includes(stored.cols as (typeof WIDTHS)[number]) ? (stored.cols as number) : DEFAULTS.cols,
      accents: stored.accents ?? DEFAULTS.accents,
      picture: stored.picture ?? DEFAULTS.picture,
    };
  } catch {
    return DEFAULTS;
  }
}

export function saveSettings(settings: PrinterSettings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    // Private mode: the settings last until the page closes.
  }
}

// The few Web Bluetooth types we use (TypeScript does not ship them).
type Characteristic = {
  properties: { write: boolean; writeWithoutResponse: boolean };
  writeValue(value: BufferSource): Promise<void>;
  writeValueWithoutResponse(value: BufferSource): Promise<void>;
};
type Service = { getCharacteristics(): Promise<Characteristic[]> };
type Server = { getPrimaryServices(): Promise<Service[]> };
type Device = { gatt?: { connected: boolean; connect(): Promise<Server>; disconnect(): void } };
type Bluetooth = {
  requestDevice(options: { acceptAllDevices: true; optionalServices: string[] }): Promise<Device>;
};

// The services small printers use for their serial data (the maker's own, or the common 0xFFE0 / 0x18F0).
const PRINTER_SERVICES = [
  "000018f0-0000-1000-8000-00805f9b34fb",
  "0000ffe0-0000-1000-8000-00805f9b34fb",
  "0000ff00-0000-1000-8000-00805f9b34fb",
  "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
  "49535343-fe7d-4ae5-8fa9-9fafd205e455",
];

export const bluetoothAvailable = () => typeof navigator !== "undefined" && "bluetooth" in navigator;

let device: Device | null = null;
let channel: Characteristic | null = null;

async function connect(): Promise<Characteristic> {
  if (channel !== null && device?.gatt?.connected) return channel;
  const bluetooth = (navigator as unknown as { bluetooth: Bluetooth }).bluetooth;
  // The phone's own picker lists the printers around; the choice is asked once per session.
  device ??= await bluetooth.requestDevice({ acceptAllDevices: true, optionalServices: PRINTER_SERVICES });
  const server = await device.gatt?.connect();
  if (server === undefined) throw new Error("no-gatt");
  for (const service of await server.getPrimaryServices()) {
    for (const found of await service.getCharacteristics()) {
      if (found.properties.write || found.properties.writeWithoutResponse) {
        channel = found;
        return found;
      }
    }
  }
  throw new Error("no-channel");
}

/** Forget the chosen printer, so the next print asks again. */
export function forgetPrinter(): void {
  device?.gatt?.disconnect();
  device = null;
  channel = null;
}

async function send(bytes: Uint8Array): Promise<void> {
  const target = await connect();
  // Printers have small buffers: short pieces, with a pause when the printer does not answer each one. A picture is
  // some 50 kB, hence pieces larger than the text needs.
  const piece = 180;
  for (let at = 0; at < bytes.length; at += piece) {
    const part = bytes.slice(at, at + piece);
    if (target.properties.writeWithoutResponse) {
      await target.writeValueWithoutResponse(part);
      await new Promise((resolve) => setTimeout(resolve, 20));
    } else await target.writeValue(part);
  }
}

/** The bytes of rows: a picture (logo, Arabic) or the printer's text, as the settings say. */
async function job(rows: Row[], settings: PrinterSettings): Promise<Uint8Array> {
  if (!settings.picture) return escposJob([rows], settings);
  return rasterJob([await receiptBitmap(rows, settings.cols, rememberedLogo())]);
}

/** Prints one copy of a receipt: the customer's or supplier's, or the office's (D-281: one copy per tap). */
export async function printReceipt(data: ReceiptData, copy: ReceiptCopy, settings: PrinterSettings): Promise<void> {
  await send(await job(layoutReceipt(data, copy, settings.cols), settings));
}

/** A short test page: the logo, a ruler as wide as the paper, the French accents, Arabic and a sample amount. */
export async function printTest(settings: PrinterSettings): Promise<void> {
  const ruler = Array.from({ length: settings.cols }, (_, i) => String((i + 1) % 10)).join("");
  const rows: Row[] = [
    { logo: true },
    { text: "TEST D'IMPRESSION", align: "center", bold: true },
    { text: ruler },
    { text: "éèêàçùôîû ÉÀ - 1 250,000 DT" },
    { text: "قاروص - ورقة تجربة", align: "right", ar: true },
    { text: ruler },
    { feed: 3 },
  ];
  await send(await job(rows, settings));
}
