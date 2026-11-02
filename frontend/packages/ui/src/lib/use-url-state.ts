import { useCallback } from "react";
import { useSearchParams } from "react-router";

import { changeParams } from "./url-params";

/** Like `useState` for a text, but kept in the address (`?name=value`): a refresh keeps it and the link can be
 * shared. An empty value leaves the address clean. Changes replace the history entry, so Back is not flooded. */
export function useUrlState(name: string, initial = ""): [string, (value: string) => void] {
  const [params, setParams] = useSearchParams();
  const value = params.get(name) ?? initial;
  const set = useCallback(
    (next: string) => changeParams(params, setParams, { [name]: next === initial ? null : next }),
    [name, initial, params, setParams],
  );
  return [value, set];
}
