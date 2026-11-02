import { useTranslation } from "@frutti/i18n";

import { PAGE_SIZES } from "../lib/use-table-view";
import { Button } from "./button";

/** The strip under a long table: "51–100 sur 200", page buttons, and the number of rows per page. Shows nothing for
 * a list that fits one page at the smallest size. */
export function Pager({
  page,
  pageSize,
  total,
  onPage,
  onPageSize,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
  onPageSize: (size: number) => void;
}) {
  const { t } = useTranslation();
  if (total <= Math.min(...PAGE_SIZES)) return null;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  // First, last, and two neighbours of the current page; gaps shown as an ellipsis.
  const shown = [...new Set([1, page - 1, page, page + 1, pageCount])].filter((n) => n >= 1 && n <= pageCount);
  shown.sort((a, b) => a - b);
  return (
    <div className="flex flex-wrap items-center justify-end gap-2 p-2 text-[0.85rem]">
      <span className="me-auto text-ink-2">
        {t("common.table.range", {
          from: (page - 1) * pageSize + 1,
          to: Math.min(page * pageSize, total),
          count: total,
        })}
      </span>
      <label className="flex items-center gap-1.5 text-ink-2">
        {t("common.table.perPage")}
        <select
          className="rounded-md border border-line bg-surface px-1.5 py-1 text-ink"
          value={pageSize}
          onChange={(event) => onPageSize(Number(event.target.value))}
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>
      <Button disabled={page <= 1} onClick={() => onPage(page - 1)}>
        {t("common.table.previous")}
      </Button>
      {shown.map((n, index) => (
        <span key={n} className="flex items-center gap-2">
          {index > 0 && n - (shown[index - 1] ?? 0) > 1 && <span className="text-ink-2">…</span>}
          <Button
            aria-current={n === page ? "page" : undefined}
            className={n === page ? "font-bold" : undefined}
            onClick={() => onPage(n)}
          >
            {n}
          </Button>
        </span>
      ))}
      <Button disabled={page >= pageCount} onClick={() => onPage(page + 1)}>
        {t("common.table.next")}
      </Button>
    </div>
  );
}
