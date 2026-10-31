import { formatMoneyInput } from "@frutti/i18n";
import { type ComponentProps } from "react";

import { typeMoney } from "../lib/type-money";
import { Input } from "./input";

type MoneyInputProps = Omit<ComponentProps<"input">, "value"> & { value?: string };

/** An amount in DT while the person types: "1250" shows "1 250", "1250,5" shows "1 250,5". */
export function MoneyInput({ value = "", onChange, ...props }: MoneyInputProps) {
  return (
    <Input
      inputMode="decimal"
      {...props}
      type="text"
      value={formatMoneyInput(value)}
      onChange={(event) => {
        typeMoney(event, value);
        onChange?.(event);
      }}
    />
  );
}
