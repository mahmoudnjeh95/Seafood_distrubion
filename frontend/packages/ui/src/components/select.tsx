import { Select as SelectPrimitive } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";

import { Icon } from "../icons";
import { cn } from "../lib/cn";
import { controlClasses } from "./input";

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;

export function SelectTrigger({ className, children, ...props }: ComponentProps<typeof SelectPrimitive.Trigger>) {
  return (
    <SelectPrimitive.Trigger
      className={cn(controlClasses, "flex items-center justify-between gap-2 text-start", className)}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon className="text-ink-2">
        <svg aria-hidden viewBox="0 0 24 24" className="size-4 fill-none stroke-current" strokeWidth={2}>
          <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

export function SelectContent({ className, children, ...props }: ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        position="popper"
        sideOffset={6}
        className={cn(
          "z-50 max-h-72 min-w-(--radix-select-trigger-width) overflow-hidden rounded-control border border-line bg-surface shadow-card",
          className,
        )}
        {...props}
      >
        <SelectPrimitive.Viewport className="p-1">{children}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

/** `detail` is drawn in the list beside the item's text only: the trigger shows the text alone. */
export function SelectItem({
  className,
  children,
  detail,
  ...props
}: ComponentProps<typeof SelectPrimitive.Item> & { detail?: ReactNode }) {
  return (
    <SelectPrimitive.Item
      className={cn(
        "flex cursor-pointer items-center justify-between gap-3 rounded-[7px] px-2.5 py-2 text-[0.9rem] outline-none select-none data-disabled:opacity-40 data-highlighted:bg-sea-soft data-highlighted:text-sea",
        className,
      )}
      {...props}
    >
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      {detail}
      <SelectPrimitive.ItemIndicator>
        <Icon name="check" className="size-4" />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  );
}
