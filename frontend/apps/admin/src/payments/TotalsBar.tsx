import { formatMoney } from "@frutti/i18n";
import { cn } from "@frutti/ui";
import type { ReactNode } from "react";

/** The bar under a règlement form: what is paid, what goes on invoices, what is left as an advance (red when
 * the invoices take more than is paid), and the form's buttons. */
export function TotalsBar({
  total,
  allocated,
  remaining,
  overAllocated,
  labels,
  children,
}: {
  total: string;
  allocated: string;
  remaining: string;
  overAllocated: boolean;
  labels: { total: string; allocated: string; remaining: string };
  children: ReactNode;
}) {
  return (
    <div
      className="sticky bottom-0 z-10 flex flex-wrap items-center gap-x-8 gap-y-3 rounded-card border border-line bg-surface p-3 shadow-md"
      aria-live="polite"
    >
      <dl className="flex flex-wrap gap-x-8 gap-y-2">
        <div>
          <dt className="text-[0.78rem] font-semibold text-ink-2">{labels.total}</dt>
          <dd className="num text-lg font-bold">{formatMoney(total)}</dd>
        </div>
        <div>
          <dt className="text-[0.78rem] font-semibold text-ink-2">{labels.allocated}</dt>
          <dd className={cn("num text-lg", overAllocated && "font-bold text-bad")}>{formatMoney(allocated)}</dd>
        </div>
        <div>
          <dt className="text-[0.78rem] font-semibold text-ink-2">{labels.remaining}</dt>
          <dd className={cn("num text-lg", overAllocated && "font-bold text-bad")}>{formatMoney(remaining)}</dd>
        </div>
      </dl>
      <div className="ms-auto flex gap-2">{children}</div>
    </div>
  );
}
