import type { ComponentProps } from "react";

import { cn } from "../lib/cn";

/** Wraps the table so a wide one scrolls inside its card instead of stretching the page. Every table looks like
 * a spreadsheet (a border around each cell, a shaded header row). `frozen` keeps the header row in view while a
 * long table scrolls inside its own frame. */
export function Table({ className, frozen = false, ...props }: ComponentProps<"table"> & { frozen?: boolean }) {
  return (
    <div className={cn("overflow-x-auto", frozen && "max-h-[calc(100vh-18rem)] min-h-48 overflow-y-auto")}>
      <table className={cn("w-full border-collapse text-[0.9rem]", className)} {...props} />
    </div>
  );
}

export function Th({ className, numeric = false, ...props }: ComponentProps<"th"> & { numeric?: boolean }) {
  return (
    <th
      className={cn(
        "sticky top-0 z-[1] border border-line bg-surface-2 px-2.5 py-2 text-[0.72rem] font-semibold tracking-[0.07em] text-ink-2 uppercase",
        numeric ? "text-end" : "text-start",
        className,
      )}
      {...props}
    />
  );
}

/** `numeric` aligns to the end of the line and uses fixed-width digits: use it for every amount and weight. */
export function Td({ className, numeric = false, ...props }: ComponentProps<"td"> & { numeric?: boolean }) {
  return (
    <td
      className={cn("border border-line px-2.5 py-[9px] align-middle", numeric && "num text-end", className)}
      {...props}
    />
  );
}

/** A header the user can click to sort by its column: ▲ ascending, ▼ descending, a second click reverses, a third
 * restores the original order. Pair it with `useTableView`. */
export function SortTh({
  sortKey,
  sort,
  onSort,
  children,
  className,
  numeric = false,
  ...props
}: Omit<ComponentProps<"th">, "onClick"> & {
  sortKey: string;
  sort: { key: string; direction: "asc" | "desc" } | null;
  onSort: (key: string) => void;
  numeric?: boolean;
}) {
  const active = sort?.key === sortKey ? sort.direction : null;
  return (
    <Th
      numeric={numeric}
      aria-sort={active === "asc" ? "ascending" : active === "desc" ? "descending" : "none"}
      className={cn("cursor-pointer select-none hover:text-ink", className)}
      {...props}
    >
      <button type="button" className="inline-flex items-center gap-1 uppercase" onClick={() => onSort(sortKey)}>
        {children}
        <span aria-hidden className={cn("text-[0.6rem]", active ? "text-sea" : "opacity-30")}>
          {active === "desc" ? "▼" : "▲"}
        </span>
      </button>
    </Th>
  );
}
