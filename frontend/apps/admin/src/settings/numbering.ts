import type { NumberLine } from "@frutti/api";

/** The next number as it reads with `prefix` typed: the server's "<prefix><separator><number>" with the new prefix. */
export function nextWithPrefix(line: NumberLine, prefix: string): string {
  return `${prefix}${line.next_number.slice(line.prefix.length)}`;
}
