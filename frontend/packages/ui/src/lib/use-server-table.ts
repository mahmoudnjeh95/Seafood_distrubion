import { useCallback, useState } from "react";
import { useSearchParams } from "react-router";

import { changeParams } from "./url-params";
import { rememberedPageSize, rememberPageSize, type TableSort } from "./use-table-view";

const SORT = "tri";
const PAGE = "page";

function sortFrom(value: string | null): TableSort {
  if (!value) return null;
  return value.startsWith("-") ? { key: value.slice(1), direction: "desc" } : { key: value, direction: "asc" };
}

/** The sort and the page of a list the server pages (`limit`, `offset`, `ordering`). Spread `params` into the list
 * query; give `sorting` to every `SortTh` and `pager(count)` to `Pager`. The sort (`?tri=-date`) and the page
 * (`?page=3`) live in the address, so a refresh or a shared link shows the same view. `backToFirstPage` goes with
 * every filter change. */
export function useServerTable(initialSize = 50) {
  const [urlParams, setUrlParams] = useSearchParams();
  const sort = sortFrom(urlParams.get(SORT));
  const page = Math.max(1, Math.floor(Number(urlParams.get(PAGE))) || 1);
  // The page size lives in storage; this makes the list draw again when it changes.
  const [, redraw] = useState(0);
  const pageSize = rememberedPageSize(initialSize);

  const update = useCallback(
    (changes: Record<string, string | null>) => changeParams(urlParams, setUrlParams, changes),
    [urlParams, setUrlParams],
  );
  const setPage = useCallback((value: number) => update({ [PAGE]: value > 1 ? String(value) : null }), [update]);

  const ordering = sort ? { ordering: sort.direction === "desc" ? `-${sort.key}` : sort.key } : {};
  return {
    params: { limit: pageSize, offset: (page - 1) * pageSize, ...ordering },
    /** The sort alone, for the Excel file of the whole list. */
    ordering,
    sorting: {
      sort,
      onSort: (key: string) => {
        const next = sort?.key !== key ? key : sort.direction === "asc" ? `-${key}` : null;
        update({ [SORT]: next, [PAGE]: null });
      },
    },
    backToFirstPage: () => setPage(1),
    pager: (total: number) => ({
      page,
      pageSize,
      total,
      onPage: setPage,
      onPageSize: (size: number) => {
        rememberPageSize(size);
        redraw((n) => n + 1);
        update({ [PAGE]: null });
      },
    }),
  };
}
