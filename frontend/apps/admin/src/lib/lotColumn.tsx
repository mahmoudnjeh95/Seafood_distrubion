import type { Line } from "./lines";
import { LotCell } from "./LotCell";

/**
 * The lot column of a line grid (`LinesGrid`'s `extra`): the lots of each row's product at `room`. With `room`
 * undefined no lot can be picked (a load from several cold rooms, D-215): the rows take the oldest lots.
 */
export function lotColumn(header: string, room: string | undefined) {
  return {
    header,
    field: "picks",
    cell: (line: Line, change: (fields: Partial<Line>) => void) => (
      <LotCell room={room ?? ""} line={line} disabled={room === undefined} onChange={(picks) => change({ picks })} />
    ),
  };
}
