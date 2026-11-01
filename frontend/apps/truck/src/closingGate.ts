import type { QueuedItem } from "./queue";

/**
 * Whether the day can be sent to the office (D-090, D-091). Every item still waiting on the phone must leave
 * first, so the office gets the day with all its sales. A refused item does not block: it is shown on every screen
 * until the driver has read it (SyncStatus), and the office has it (P3-T07d).
 */
export function closingGate(input: {
  queue: QueuedItem[];
  online: boolean;
  /** A send of the closing is already running. */
  busy: boolean;
}): { waiting: number; canSend: boolean } {
  const waiting = input.queue.filter((item) => item.status === "pending").length;
  return {
    waiting,
    canSend: !input.busy && input.online && waiting === 0,
  };
}
