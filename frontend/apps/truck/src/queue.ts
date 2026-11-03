import type {
  Deliver,
  MyBoxPickupWrite,
  MyFieldPurchaseCreate,
  NotDelivered,
  RoadExpenseWrite,
  RoadLossWrite,
  RoadPaymentWrite,
  SaleWrite,
} from "@frutti/api";
import { useEffect, useState } from "react";

// What the phone could not send yet (P3-T07b and T07c, D-097). They live in IndexedDB, so they survive closing the
// app or restarting the phone, until the server has taken them.

interface Waiting {
  /** The item's `client_uuid`: the server never makes two records from the same one. */
  uuid: string;
  createdAt: string;
  /** What the driver would call it: the customer, the category, the product. */
  label: string;
  /** "pending": waiting for a connection. "refused": the server said no; it stays until someone looks at it. */
  status: "pending" | "refused";
  error: string;
  /** The office has been told about a refusal (P3-T07d). */
  reported?: boolean;
}

export interface QueuedSale extends Waiting {
  kind: "sale";
  /** With `sold_at`, the moment the sale was made by the phone's clock (D-133). */
  data: SaleWrite;
  /** What the screen showed when the sale was made, for the receipt on the phone. */
  estimate: {
    /** `nameAr`: the product's Arabic name, for the printed receipt (D-282). */
    lines: { name: string; nameAr?: string; kilos: string; amount: string }[];
    total: string;
    paid: string;
  };
}

export interface QueuedExpense extends Waiting {
  kind: "expense";
  /** The receipt photo travels with it (IndexedDB keeps files). */
  data: RoadExpenseWrite;
}

export interface QueuedLoss extends Waiting {
  kind: "loss";
  data: RoadLossWrite;
}

export interface QueuedPayment extends Waiting {
  kind: "payment";
  data: RoadPaymentWrite;
}

/** Boxes a client hands back to the truck (P1-T14e): the `client_uuid` in the data makes a retry post once. */
export interface QueuedPickup extends Waiting {
  kind: "pickup";
  data: MyBoxPickupWrite;
}

/** A purchase at the port (P3-T12b, D-158): the `client_uuid` in the data makes a retry make one purchase. */
export interface QueuedPurchase extends Waiting {
  kind: "purchase";
  data: MyFieldPurchaseCreate;
  /** The photo of the supplier's paper, sent after the purchase (IndexedDB keeps files, D-159). */
  paper?: File;
}

/** The delivery of a BL of the load (D-178): the `client_uuid` in the data records it once. */
export interface QueuedDelivery extends Waiting {
  kind: "delivery";
  saleId: number;
  data: Deliver;
  /** Kilos per product that leave the truck with it, for the stock shown meanwhile. */
  kilos: Record<number, number>;
}

/** A BL of the load not delivered (D-178): nothing leaves the truck. */
export interface QueuedNotDelivered extends Waiting {
  kind: "not_delivered";
  saleId: number;
  data: NotDelivered;
}

export type QueuedItem =
  | QueuedSale
  | QueuedExpense
  | QueuedLoss
  | QueuedPayment
  | QueuedPickup
  | QueuedPurchase
  | QueuedDelivery
  | QueuedNotDelivered;

const DATABASE = "frutti-truck";
const STORE = "sales";
const listeners = new Set<() => void>();

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: "uuid" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB"));
  });
}

async function run<T>(mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const database = await open();
  try {
    return await new Promise<T>((resolve, reject) => {
      const request = work(database.transaction(STORE, mode).objectStore(STORE));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error ?? new Error("IndexedDB"));
    });
  } finally {
    database.close();
  }
}

function changed(): void {
  listeners.forEach((listener) => listener());
}

/** Oldest first, the order they were made in. */
export async function listQueue(): Promise<QueuedItem[]> {
  const rows = await run("readonly", (store) => store.getAll() as IDBRequest<QueuedItem[]>);
  return rows.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export async function enqueue(item: QueuedItem): Promise<void> {
  await run("readwrite", (store) => store.put(item));
  changed();
}

export async function removeQueued(uuid: string): Promise<void> {
  await run("readwrite", (store) => store.delete(uuid));
  changed();
}

export async function markReported(item: QueuedItem): Promise<void> {
  await run("readwrite", (store) => store.put({ ...item, reported: true }));
  changed();
}

export async function markRefused(item: QueuedItem, error: string): Promise<void> {
  await run("readwrite", (store) => store.put({ ...item, status: "refused", error }));
  changed();
}

/** The queue, kept up to date on screen. */
export function useQueue(): QueuedItem[] {
  const [queue, setQueue] = useState<QueuedItem[]>([]);
  useEffect(() => {
    let alive = true;
    const refresh = () => {
      listQueue()
        .then((rows) => alive && setQueue(rows))
        .catch(() => undefined);
    };
    refresh();
    listeners.add(refresh);
    return () => {
      alive = false;
      listeners.delete(refresh);
    };
  }, []);
  return queue;
}

/**
 * When a waiting sale was made (D-133). One kept by an earlier version of the app has no `sold_at`: it was put
 * in the queue the moment it was made, so that time is used.
 */
export function madeAtOf(sale: QueuedSale): string {
  return sale.data.sold_at ?? sale.createdAt;
}

/** Kilos per product already promised by waiting sales, deliveries and losses: they are no longer in the truck. */
export function pendingKilos(queue: QueuedItem[]): Record<number, number> {
  const kilos: Record<number, number> = {};
  for (const item of queue) {
    if (item.status !== "pending") continue;
    if (item.kind === "sale") {
      for (const line of item.data.lines) kilos[line.product] = (kilos[line.product] ?? 0) + Number(line.quantity);
    } else if (item.kind === "loss") {
      kilos[item.data.product] = (kilos[item.data.product] ?? 0) + Number(item.data.quantity);
    } else if (item.kind === "delivery") {
      for (const [product, kg] of Object.entries(item.kilos))
        kilos[Number(product)] = (kilos[Number(product)] ?? 0) + kg;
    }
  }
  return kilos;
}
