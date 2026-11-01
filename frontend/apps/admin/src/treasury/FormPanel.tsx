import { cn } from "@frutti/ui";
import type { ReactNode } from "react";

/** A titled box of a treasury form, as the Perfaxis forms group their fields ("Informations encaissement", "Informations
 * client"): the title sits on a rule, the fields below it. */
export function FormPanel({ title, className, children }: { title: string; className?: string; children: ReactNode }) {
  return (
    <section
      className={cn("flex flex-col gap-3 rounded-card border border-line bg-surface p-4 shadow-card", className)}
    >
      <h2 className="border-b border-line pb-2 text-[0.95rem] font-semibold text-sea">{title}</h2>
      {children}
    </section>
  );
}
