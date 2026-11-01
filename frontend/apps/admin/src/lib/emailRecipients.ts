/** The recipients of an e-mailed document (D-222): the party's addresses, each ticked or not for this send, and the
 * addresses typed for this send only. Pure functions, so the window only shows them. */

// The server takes ten addresses at most.
export const MAX_RECIPIENTS = 10;

const isEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);

export const sameAddress = (first: string, second: string) => first.toLowerCase() === second.toLowerCase();

/** The addresses in a typed text, split on commas, semicolons or spaces; null when one of them is not an e-mail. */
export function typedAddresses(typed: string): string[] | null {
  const values = typed
    .split(/[,;\s]+/)
    .map((value) => value.trim())
    .filter(Boolean);
  return values.every(isEmail) ? values : null;
}

/** The addresses that go out: the offered ones that are still ticked. */
export const chosenAddresses = (offered: string[], unticked: string[]) =>
  offered.filter((address) => !unticked.some((other) => sameAddress(other, address)));

/** Ticks or unticks one address; `unticked` lists the ones left out of this send. */
export function setTicked(unticked: string[], address: string, ticked: boolean): string[] {
  const others = unticked.filter((other) => !sameAddress(other, address));
  return ticked ? others : [...others, address];
}

/** Adds the typed addresses that are not offered yet, each once, and ticks the typed ones back. */
export function addTyped(
  added: string[],
  offered: string[],
  unticked: string[],
  typed: string[],
): { added: string[]; unticked: string[] } {
  const fresh = typed.filter(
    (value, index) =>
      !offered.some((known) => sameAddress(known, value)) &&
      typed.findIndex((other) => sameAddress(other, value)) === index,
  );
  return {
    added: [...added, ...fresh],
    unticked: unticked.filter((other) => !typed.some((value) => sameAddress(value, other))),
  };
}
