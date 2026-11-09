import type { QuoteStatusEnum } from "@frutti/api";
import { canAccess, type Session } from "@frutti/auth";
import { currentLanguage } from "@frutti/i18n";
import type { QueryClient } from "@tanstack/react-query";

const NO_BREAK_SPACE = String.fromCharCode(0xa0);

/** A discount rate as the API sends it, "7.50" → "7,5 %" (Western digits in Arabic too, D-025). */
export function formatRate(rate: string): string {
  const formatter = new Intl.NumberFormat(`${currentLanguage()}-TN-u-nu-latn`, { maximumFractionDigits: 2 });
  return `${formatter.format(rate as Intl.StringNumericLiteral)}${NO_BREAK_SPACE}%`;
}

/** After a quote changes, refresh the quote lists and pages. */
export function refreshAfterQuote(queryClient: QueryClient) {
  return queryClient.invalidateQueries({
    predicate: (query) => typeof query.queryKey[0] === "string" && query.queryKey[0].startsWith("/api/v1/quotes"),
  });
}

/** The server refuses quote changes from other roles; this only avoids showing buttons that would fail. */
export function canWriteQuotes(session: Session): boolean {
  return canAccess(session, "quotes", "write");
}

export const QUOTE_STATUSES: QuoteStatusEnum[] = ["draft", "sent", "accepted", "refused", "expired"];

// The prototype's "Devis en cours": sent in sea blue, accepted green, refused red, waiting too long orange.
export const STATUS_TONES = {
  draft: "neutral",
  sent: "sea",
  accepted: "good",
  refused: "bad",
  expired: "warn",
} as const satisfies Record<QuoteStatusEnum, string>;
