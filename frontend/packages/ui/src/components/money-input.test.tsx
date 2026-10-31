import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, test } from "vitest";

import { MoneyInput } from "./money-input";

afterEach(cleanup);

// Intl's thousands separator is a no-break space: the tests compare with a plain space.
const shownIn = (label: string) => screen.getByLabelText<HTMLInputElement>(label).value.replace(/\s/g, " ");

function Amount({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="amount">Montant</label>
      <MoneyInput id="amount" value={value} onChange={(event) => setValue(event.target.value)} />
      <output data-testid="stored">{value}</output>
    </>
  );
}

test("typing shows the thousands separators and keeps the decimal comma", async () => {
  const user = userEvent.setup();
  render(<Amount />);

  await user.type(screen.getByLabelText("Montant"), "1250000");
  expect(shownIn("Montant")).toBe("1 250 000");

  await user.clear(screen.getByLabelText("Montant"));
  await user.type(screen.getByLabelText("Montant"), "1250.5");
  expect(shownIn("Montant")).toBe("1 250,5");
  expect(screen.getByTestId("stored").textContent).toBe("1 250,5");
});

test("an amount that is already stored is shown with separators", () => {
  render(<Amount initial="1250.000" />);

  expect(shownIn("Montant")).toBe("1 250,000");
});

test("backspace over a separator removes the digit before it", async () => {
  const user = userEvent.setup();
  render(<Amount initial="1 250" />);
  const input = screen.getByLabelText<HTMLInputElement>("Montant");

  input.setSelectionRange(2, 2);
  await user.keyboard("{Backspace}");

  expect(shownIn("Montant")).toBe("250");
});
