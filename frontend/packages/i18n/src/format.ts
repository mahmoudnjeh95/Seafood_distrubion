import { currentLanguage, i18n, type Language } from "./i18n";

// Tunisian conventions: 1 250,000 in French, 1.250,000 in Arabic, always with Western digits.
const LOCALES: Record<Language, string> = { fr: "fr-TN", ar: "ar-TN" };
const NO_BREAK_SPACE = " ";

/** A decimal as the API sends it, e.g. "1250.000". Never a JavaScript number (ARCHITECTURE §4.1). */
type DecimalString = string;

function threeDecimals(value: DecimalString, language: Language): string {
  if (!/^-?\d+(\.\d+)?$/.test(value)) throw new TypeError(`Not a decimal string: ${JSON.stringify(value)}`);
  const formatter = new Intl.NumberFormat(LOCALES[language], { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  // Given a string, Intl formats the exact decimal: no float is ever created.
  return formatter.format(value as Intl.StringNumericLiteral);
}

/** "1250" → "1 250,000 DT" */
export function formatMoney(amount: DecimalString, language: Language = currentLanguage()): string {
  return `${threeDecimals(amount, language)}${NO_BREAK_SPACE}${i18n.t("common.currency", { lng: language })}`;
}

/** "12.5" → "12,500 kg" */
export function formatQuantity(kilograms: DecimalString, language: Language = currentLanguage()): string {
  return `${threeDecimals(kilograms, language)}${NO_BREAK_SPACE}kg`;
}

/** "2026-10-09" or a full ISO timestamp → "09/10/2026", read in Tunisian time. */
export function formatDate(iso: string, language: Language = currentLanguage()): string {
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  const date = new Date(dateOnly ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(date.getTime())) throw new TypeError(`Not an ISO date: ${JSON.stringify(iso)}`);
  return new Intl.DateTimeFormat(LOCALES[language], {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    // A plain date has no time zone; a timestamp is shown in the company's time.
    timeZone: dateOnly ? "UTC" : "Africa/Tunis",
  }).format(date);
}

/** A timestamp → "09/10/2026 14:05", in Tunisian time. Sale prices change several times a day. */
export function formatDateTime(iso: string, language: Language = currentLanguage()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) throw new TypeError(`Not an ISO timestamp: ${JSON.stringify(iso)}`);
  return new Intl.DateTimeFormat(LOCALES[language], {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "Africa/Tunis",
  }).format(date);
}

/** A change in percent: "1.3" → "+1,3 %", "-10.0" → "-10,0 %", "0.0" → "0,0 %". */
export function formatPercent(percent: DecimalString, language: Language = currentLanguage()): string {
  if (!/^-?\d+(\.\d+)?$/.test(percent)) throw new TypeError(`Not a decimal string: ${JSON.stringify(percent)}`);
  const formatter = new Intl.NumberFormat(LOCALES[language], {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    signDisplay: "exceptZero",
  });
  return `${formatter.format(percent as Intl.StringNumericLiteral)}${NO_BREAK_SPACE}%`;
}

/** "-18.0" → "-18 °C", "2.5" → "2,5 °C" */
export function formatTemperature(celsius: DecimalString, language: Language = currentLanguage()): string {
  if (!/^-?\d+(\.\d+)?$/.test(celsius)) throw new TypeError(`Not a decimal string: ${JSON.stringify(celsius)}`);
  const formatter = new Intl.NumberFormat(LOCALES[language], { maximumFractionDigits: 1 });
  return `${formatter.format(celsius as Intl.StringNumericLiteral)}${NO_BREAK_SPACE}°C`;
}

/**
 * What a person typed in a number field → the decimal string the API expects, or `null` when it is not
 * a number with at most `maxDecimals` decimals. A comma, a dot or the Arabic separator are all accepted,
 * and spaces between thousands are ignored: "1 250,5" → "1250.5". Never goes through a JavaScript number.
 */
export function parseDecimalInput(text: string, maxDecimals: number): string | null {
  // \s also covers the no-break spaces that Intl puts between thousands.
  const compact = text.replace(/\s/g, "").replace(/[,\u066b]/, ".");
  const decimals = maxDecimals > 0 ? `(\\.\\d{1,${maxDecimals}})?` : "";
  return new RegExp(`^-?\\d+${decimals}$`).test(compact) ? compact : null;
}

/** The thousands separator of the French format (Intl's no-break space), as amount fields show it while typing. */
const THOUSANDS_SEPARATOR =
  new Intl.NumberFormat(LOCALES.fr).formatToParts(1000).find((part) => part.type === "group")?.value ?? NO_BREAK_SPACE;

/** The sign, the whole digits and the decimals of a typed amount. Only the first decimal separator counts. */
function splitTypedAmount(typed: string): { negative: boolean; whole: string; decimals: string | null } {
  const compact = typed.replace(/\s/g, "");
  const negative = compact.startsWith("-");
  const body = negative ? compact.slice(1) : compact;
  const separator = body.search(/[.,٫]/);
  const whole = (separator === -1 ? body : body.slice(0, separator)).replace(/\D/g, "");
  const decimals = separator === -1 ? null : body.slice(separator + 1).replace(/\D/g, "");
  return { negative, whole, decimals };
}

/**
 * What an amount field shows while the person types: "1250" → "1 250", "1250.5" → "1 250,5",
 * "1250000" → "1 250 000".
 * The decimal comma stays and nothing is cut: a fourth decimal is still shown, and parseDecimalInput refuses it.
 * The API never gets this text: it gets the string parseDecimalInput returns from it.
 */
export function formatMoneyInput(typed: string): string {
  const { negative, whole, decimals } = splitTypedAmount(typed);
  const digits = whole.replace(/^0+(?=\d)/, "");
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, THOUSANDS_SEPARATOR);
  return `${negative ? "-" : ""}${grouped}${decimals === null ? "" : `,${decimals}`}`;
}

/**
 * Where the caret goes in the formatted text: after the same sign, digits and decimal comma that were before
 * the caret in the typed text. `caret` is the typed text's caret position; `formatted` is formatMoneyInput(typed).
 */
export function moneyInputCaret(typed: string, caret: number, formatted: string): number {
  const before = splitTypedAmount(typed.slice(0, caret));
  const passed =
    (before.negative ? 1 : 0) + before.whole.length + (before.decimals === null ? 0 : 1 + before.decimals.length);
  let position = 0;
  let seen = 0;
  for (let index = 0; index < formatted.length && seen < passed; index += 1) {
    if (/[-\d,]/.test(formatted.charAt(index))) {
      seen += 1;
      position = index + 1;
    }
  }
  return position;
}
