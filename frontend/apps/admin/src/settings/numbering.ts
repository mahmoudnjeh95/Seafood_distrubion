import type { NumberLine } from "@frutti/api";

/** What a draft reads when its kind has no draft prefix (D-283), as the server writes it. */
export const DRAFT_WORD = "BROUILLON";

/** The next number as it reads with `prefix` typed: the server's "<prefix><separator><number>" with the new prefix.
 * With `draft`, the next provisional reference of a draft (D-283), from its own counter. */
export function nextWithPrefix(line: NumberLine, prefix: string, draft = false): string {
  const next = draft ? line.next_draft_number : line.next_number;
  const saved = draft ? line.draft_prefix || DRAFT_WORD : line.prefix;
  return `${prefix}${next.slice(saved.length)}`;
}
