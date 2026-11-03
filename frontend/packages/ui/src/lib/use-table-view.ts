import { useMemo, useState } from "react";

export type SortValue = string | number | null | undefined;
export type SortDirection = "asc" | "desc";
export type TableSort = { key: string; direction: SortDirection } | null;

export const PAGE_SIZES = [25, 50, 100, 200] as const;

const PAGE_SIZE_KEY = "frutti.pageSize";

/** The rows per page the user picked last time, on any list; storage can be blocked, so it is only a convenience. */
export function rememberedPageSize(fallback: number): number {
  try {
    const saved = Number(window.localStorage.getItem(PAGE_SIZE_KEY));
    return (PAGE_SIZES as readonly number[]).includes(saved) ? saved : fallback;
  } catch {
    return fallback;
  }
}

export function rememberPageSize(size: number): void {
  try {
    window.localStorage.setItem(PAGE_SIZE_KEY, String(size));
  } catch {
    // Not remembered: the list still works.
  }
}

function compare(a: SortValue, b: SortValue): number {
  // Empty values always go last, whatever the direction.
  if (a == null || a === "") return b == null || b === "" ? 0 : 1;
  if (b == null || b === "") return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "fr", { numeric: true, sensitivity: "base" });
}

/** Sorts and pages rows already loaded in the browser. `accessors` gives, for each sortable column key, the value to
 * compare (return a number for amounts, so "10" sorts after "9"). A click on a header cycles ascending, descending,
 * back to the original order. Changing the sort or the page size goes back to page 1. */
export function useTableView<Row>(
  rows: readonly Row[],
  accessors: Record<string, (row: Row) => SortValue>,
  { pageSize: initialSize = 50 }: { pageSize?: number } = {},
) {
  const [sort, setSort] = useState<TableSort>(null);
  const [pageSize, setPageSizeState] = useState(() => rememberedPageSize(initialSize));
  const [requestedPage, setPage] = useState(1);

  const sorted = useMemo(() => {
    const accessor = sort ? accessors[sort.key] : undefined;
    if (!sort || !accessor) return rows;
    const sign = sort.direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const va = accessor(a);
      const vb = accessor(b);
      const emptyA = va == null || va === "";
      const emptyB = vb == null || vb === "";
      if (emptyA || emptyB) return compare(va, vb);
      return sign * compare(va, vb);
    });
    // `accessors` is usually an inline object: the rows and the sort decide.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sort]);

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const page = Math.min(requestedPage, pageCount);
  const start = (page - 1) * pageSize;

  return {
    rows: sorted.slice(start, start + pageSize),
    sort,
    toggleSort: (key: string) => {
      setSort((current) => {
        if (current?.key !== key) return { key, direction: "asc" };
        return current.direction === "asc" ? { key, direction: "desc" } : null;
      });
      setPage(1);
    },
    pager: {
      page,
      pageSize,
      total: sorted.length,
      onPage: setPage,
      onPageSize: (size: number) => {
        setPageSizeState(size);
        rememberPageSize(size);
        setPage(1);
      },
    },
  };
}
