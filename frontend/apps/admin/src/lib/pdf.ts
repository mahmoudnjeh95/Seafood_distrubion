/** The PDF of a document is made by a background job: ask, and ask again until it is ready (D-071). */

export type PdfKind =
  | "quote"
  | "invoice"
  | "credit_note"
  | "receipt"
  | "partner_statement"
  | "delivery_note"
  | "supplier_receipt"
  | "bank_deposit";

export class PdfError extends Error {}

const POLL_MS = 1000;
const GIVE_UP_AFTER_MS = 60_000;

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Fetches the finished PDF as a blob. Throws `PdfError` with the server's reason when it cannot be made. */
export async function fetchPdf(kind: PdfKind, id: number): Promise<Blob> {
  const started = Date.now();
  let retry = true;
  for (;;) {
    const response = await fetch(`/api/v1/documents/${kind}/${id}/pdf${retry ? "?retry=1" : ""}`, {
      credentials: "same-origin",
    });
    retry = false;
    if (response.status === 200) return response.blob();
    if (response.status === 202) {
      if (Date.now() - started > GIVE_UP_AFTER_MS) throw new PdfError("timeout");
      await wait(POLL_MS);
      continue;
    }
    if (response.status === 400) {
      const body = (await response.json().catch(() => null)) as unknown;
      const first = Array.isArray(body) ? (body as unknown[])[0] : undefined;
      throw new PdfError(typeof first === "string" ? first : "refused");
    }
    throw new PdfError(response.status === 500 ? "failed" : `status ${response.status}`);
  }
}

/** Opens the PDF in a new tab (the tab is opened at the click, so the browser does not block it). */
export async function openPdf(kind: PdfKind, id: number): Promise<void> {
  const tab = window.open("", "_blank");
  try {
    const blob = await fetchPdf(kind, id);
    const url = URL.createObjectURL(blob);
    if (tab) tab.location.href = url;
    else window.location.href = url;
    // Kept for a minute: the tab needs the address to load it.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (error) {
    tab?.close();
    throw error;
  }
}

/** Opens the PDF made on the spot by the server in a new tab (the tab is opened at the click, so it is not blocked). */
export async function openStatement(url: string): Promise<void> {
  const tab = window.open("", "_blank");
  try {
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) throw new Error(`status ${response.status}`);
    const address = URL.createObjectURL(await response.blob());
    if (tab) tab.location.href = address;
    else window.location.href = address;
    // Kept for a minute: the tab needs the address to load it.
    setTimeout(() => URL.revokeObjectURL(address), 60_000);
  } catch (error) {
    tab?.close();
    throw error;
  }
}
