import { cn } from "@frutti/ui";

/** One figure of a règlement form's strip: a label over a bold amount (red when `bad`). */
export function Figure({ label, value, bad = false }: { label: string; value: string; bad?: boolean }) {
  return (
    <div>
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("num font-bold", bad && "text-bad")}>{value}</dd>
    </div>
  );
}
