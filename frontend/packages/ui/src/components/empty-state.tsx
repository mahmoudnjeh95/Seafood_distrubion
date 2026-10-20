import type { ReactNode } from "react";

import type { IllustrationName } from "../icon-names";
import { Illustration } from "../icons";
import { Card } from "./card";

/** A screen that has nothing to show yet: a drawing, one sentence, and optionally what to do next. */
export function EmptyState({
  illustration,
  title,
  children,
}: {
  illustration: IllustrationName;
  title: string;
  children?: ReactNode;
}) {
  return (
    <Card className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-center sm:gap-6">
      <div className="grid h-[110px] w-full flex-none sm:w-40 place-items-center rounded-control bg-radial-[120%_90%_at_30%_20%] from-tile-a to-tile-b">
        <Illustration name={illustration} className="h-[80%] w-[72%]" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <h2>{title}</h2>
        {children && <div className="text-ink-2">{children}</div>}
      </div>
    </Card>
  );
}
