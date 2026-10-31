import { formatMoneyInput, moneyInputCaret } from "@frutti/i18n";
import { type ChangeEvent } from "react";

/**
 * Types into an amount field: the text is shown with its thousands separators and the caret stays where the person
 * is typing. `previous` is the value the field held before this change. Call it from onChange, and show the field's
 * value as formatMoneyInput(value); the event's target then holds the shown text, which parseDecimalInput reads.
 */
export function typeMoney(event: ChangeEvent<HTMLInputElement>, previous: string): void {
  const input = event.currentTarget;
  const shown = formatMoneyInput(previous);
  let typed = input.value;
  let caret = input.selectionStart ?? typed.length;
  // Backspace or Delete on a thousands separator: the digit beside it goes too, or the separator comes back.
  const removedSeparator =
    typed.length === shown.length - 1 &&
    typed === shown.slice(0, caret) + shown.slice(caret + 1) &&
    /\s/.test(shown.charAt(caret));
  if (removedSeparator) {
    const digitAt = (event.nativeEvent as InputEvent).inputType === "deleteContentForward" ? caret : caret - 1;
    if (/\d/.test(typed.charAt(digitAt))) {
      typed = typed.slice(0, digitAt) + typed.slice(digitAt + 1);
      caret = digitAt;
    }
  }
  const text = formatMoneyInput(typed);
  const at = moneyInputCaret(typed, caret, text);
  input.value = text;
  input.setSelectionRange(at, at);
}
