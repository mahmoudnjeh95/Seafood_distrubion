import { useState } from "react";

import { rememberedPageSize, rememberPageSize, type TableSort } from "./use-table-view";

/** The sort and the page of a list the server pages (`limit`, `offset`, `ordering`). Spread `params` into the list
 * query; give `sorting` to every `SortTh` and `pager(count)` to `Pager`. `backToFirstPage` goes with every filter
 * change. */
export function useServerTable(initialSize = 50) {
  const [sort, setSort] = useState<TableSort>(null);
  const [pageSize, setPageSize] = useState(() => rememberedPageSize(initialSize));
  const [page, setPage] = useState(1);
  return {
    params: {
      limit: pageSize,
      offset: (page - 1) * pageSize,
      ...(sort ? { ordering: sort.direction === "desc" ? `-${sort.key}` : sort.key } : {}),
    },
    sorting: {
      sort,
      onSort: (key: string) => {
        setSort((current) => {
          if (current?.key !== key) return { key, direction: "asc" };
          return current.direction === "asc" ? { key, direction: "desc" } : null;
        });
        setPage(1);
      },
    },
    backToFirstPage: () => setPage(1),
    pager: (total: number) => ({
      page,
      pageSize,
      total,
      onPage: setPage,
      onPageSize: (size: number) => {
        setPageSize(size);
        rememberPageSize(size);
        setPage(1);
      },
    }),
  };
}
