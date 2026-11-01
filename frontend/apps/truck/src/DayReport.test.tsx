import type { MyDaySummary } from "@frutti/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { DayReport } from "./DayReport";
import type { QueuedItem, QueuedSale } from "./queue";

let queue: QueuedItem[] = [];
let problem: "offline" | "session" | "server" | null = null;

vi.mock("./queue", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./queue")>()),
  useQueue: () => queue,
}));

vi.mock("./sync", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./sync")>()),
  useSyncProblem: () => problem,
}));

function waitingSale(uuid: string): QueuedItem {
  return {
    kind: "sale",
    uuid,
    createdAt: "2026-10-13T08:00:00.000Z",
    label: "Client",
    status: "pending",
    error: "",
    data: {} as QueuedSale["data"],
    estimate: { lines: [], total: "0.000", paid: "0.000" },
  };
}

const product = {
  product_id: 1,
  product_name: "Dorade royale",
  opening: "7.000",
  loaded: "0.000",
  sold: "2.000",
  lost: "0.000",
  returned: "0.000",
  remaining: "5.000",
  unexplained: "0.000",
};

/** A day's answer; `figures` overrides or adds figures (a day kept before a figure existed has none of it). */
function day(products: object[], closing: MyDaySummary["closing"] = null, figures: object = {}): MyDaySummary {
  return {
    summary: {
      date: "2026-10-13",
      truck_name: "Camion 1",
      driver_name: "Sami",
      opening_cash: "20.000",
      sales_count: 1,
      sales_total: "56.000",
      cash_received: "56.000",
      payments_cash: "0.000",
      other_payments: "0.000",
      on_credit: "0.000",
      expenses_total: "0.000",
      expected_cash: "76.000",
      products,
      ...figures,
    },
    closing,
  } as unknown as MyDaySummary;
}

function markup(data: MyDaySummary): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <DayReport data={data} sending={false} error="" onSend={() => undefined} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  queue = [];
  problem = null;
  vi.stubGlobal("navigator", { onLine: true });
});

afterEach(() => vi.unstubAllGlobals());

test("a day shows what the truck held when it started, and no gap when the records explain it (D-130)", () => {
  const html = markup(day([product]));

  expect(html).toMatch(/Au départ 7,000\skg/);
  expect(html).toMatch(/Reste.*5,000\skg/);
  expect(html).not.toContain("Prévenez le bureau");
});

test("kilos the day's records do not explain are shown in red (D-130)", () => {
  const html = markup(day([{ ...product, remaining: "3.000", unexplained: "-2.000" }]));

  expect(html).toMatch(/text-bad[^>]*>Écart de -2,000\skg/);
  expect(html).toContain("Prévenez le bureau");
});

test("a day sent before the opening stock existed is shown as it was sent, without it", () => {
  const old = Object.fromEntries(
    Object.entries(product).filter(([name]) => name !== "opening" && name !== "unexplained"),
  );

  const html = markup(day([old]));

  expect(html).toContain("Dorade royale");
  expect(html).not.toContain("Au départ");
  expect(html).not.toContain("Écart de");
});

test("sales still waiting on the phone block the send, say how many and why, and offer a retry (D-129)", () => {
  queue = [waitingSale("1"), waitingSale("2")];
  problem = "server";

  const html = markup(day([product]));

  expect(html).toContain("2 envois ne sont pas encore partis vers le bureau");
  expect(html).toContain("Le serveur est occupé ou redémarre");
  expect(html).toContain("Réessayer l&#x27;envoi");
  // The send button is there and disabled: the gate is the one of closingGate.ts.
  expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Envoyer ma journée au bureau/);
});

test("the answer to the office's question waits for the phone's sales too", () => {
  queue = [waitingSale("1")];
  const asked = {
    id: 1,
    status: "justification",
    expected_cash: "76.000",
    driver_note: "",
    review_note: "Il manque 6 DT",
    submitted_at: "2026-10-13T12:00:00Z",
  } as MyDaySummary["closing"];

  const html = markup(day([product], asked));

  expect(html).toContain("Le bureau demande : Il manque 6 DT");
  expect(html).toContain("1 envoi n&#x27;est pas encore parti vers le bureau");
});

test("a day already sent shows no form and no waiting notice", () => {
  queue = [waitingSale("1")];
  const sent = {
    id: 1,
    status: "submitted",
    expected_cash: "76.000",
    driver_note: "",
    review_note: "",
    submitted_at: "2026-10-13T12:00:00Z",
  } as MyDaySummary["closing"];

  const html = markup(day([product], sent));

  expect(html).toContain("Journée envoyée au bureau");
  expect(html).not.toContain("Envoyer ma journée au bureau");
  expect(html).not.toContain("pas encore parti");
});

const sentClosing = {
  id: 1,
  status: "submitted",
  expected_cash: "76.000",
  driver_note: "",
  review_note: "",
  submitted_at: "2026-10-13T12:00:00Z",
  changed_since_sent: false,
} as NonNullable<MyDaySummary["closing"]>;

test("a day a new load reopened is sent again, and the cash already handed over is shown (D-134)", () => {
  const reopened = { ...sentClosing, status: "reopened" as const };

  const html = markup(day([product], reopened, { handed_over: "76.000", expected_cash: "28.000" }));

  expect(html).toContain("Journée rouverte : le camion a été rechargé");
  expect(html).toMatch(/Déjà remis au bureau<\/span><span>76,000\sDT/);
  expect(html).toContain("seul l&#x27;argent qui vous reste dans la caisse est compté");
  expect(html).toContain("Envoyer ma journée au bureau");
  expect(html).not.toContain("Journée envoyée au bureau");
});

test("the driver is not asked to count the cash: the day shows what they should hold (D-213)", () => {
  const html = markup(day([product]));

  expect(html).not.toContain('id="counted-cash"');
  expect(html).toContain("Argent attendu dans la caisse");
  expect(html).toContain("Envoyer ma journée au bureau");
});

test("a day never reopened shows no cash handed over", () => {
  expect(markup(day([product], null, { handed_over: "0.000" }))).not.toContain("Déjà remis au bureau");
  // A day sent before the figure existed has none in its kept figures.
  expect(markup(day([product], sentClosing))).not.toContain("Déjà remis au bureau");
});

test("a sent day whose records changed is corrected by the office, not sent again by the driver (D-220)", () => {
  const html = markup(day([product], { ...sentClosing, changed_since_sent: true }));

  expect(html).toContain("Les chiffres de la journée ont changé depuis l&#x27;envoi");
  expect(html).toContain("Le bureau corrige la journée");
  expect(html).not.toContain("Envoyer ma journée au bureau");
});

test("a justification asked on a day whose records did not move is answered by sending it again (D-220)", () => {
  const asked = { ...sentClosing, status: "justification" as const, review_note: "Expliquez" };

  const html = markup(day([product], asked));

  expect(html).toContain("Envoyer ma journée au bureau");
});
