import { expect, test } from "vitest";

import { closingGate } from "./closingGate";
import type { QueuedItem, QueuedSale } from "./queue";

function item(uuid: string, status: "pending" | "refused"): QueuedItem {
  return {
    kind: "sale",
    uuid,
    createdAt: "2026-10-13T08:00:00.000Z",
    label: "Client",
    status,
    error: "",
    data: {} as QueuedSale["data"],
    estimate: { lines: [], total: "0.000", paid: "0.000" },
  };
}

const idle = { busy: false };

test("a sale still waiting on the phone blocks the closing, even when online", () => {
  expect(closingGate({ queue: [item("1", "pending")], online: true, ...idle })).toEqual({
    waiting: 1,
    canSend: false,
  });
});

test("every waiting item counts, and the closing waits for all of them", () => {
  expect(closingGate({ queue: [item("1", "pending"), item("2", "pending")], online: true, ...idle })).toEqual({
    waiting: 2,
    canSend: false,
  });
});

test("a refused item does not block the closing", () => {
  expect(closingGate({ queue: [item("1", "refused")], online: true, ...idle })).toEqual({
    waiting: 0,
    canSend: true,
  });
});

test("no connection blocks the closing even with an empty queue", () => {
  expect(closingGate({ queue: [], online: false, ...idle })).toEqual({ waiting: 0, canSend: false });
});

test("the closing must not be sent twice at once", () => {
  expect(closingGate({ queue: [], online: true, busy: true }).canSend).toBe(false);
  expect(closingGate({ queue: [], online: true, ...idle }).canSend).toBe(true);
});

test("once the waiting sale has gone, the closing can be sent", () => {
  const before = closingGate({ queue: [item("1", "pending")], online: true, ...idle });
  const after = closingGate({ queue: [], online: true, ...idle });
  expect(before.canSend).toBe(false);
  expect(after.canSend).toBe(true);
});
