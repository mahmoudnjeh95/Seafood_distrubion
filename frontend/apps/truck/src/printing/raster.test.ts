import { expect, test } from "vitest";

import { splitLevel } from "./raster";

test("the split level falls between the logo's ink and the paper (D-282)", () => {
  // A light-blue logo (grey 170) on white paper: the split is between them, so the logo prints solid black.
  const grey = [...Array<number>(80).fill(255), ...Array<number>(20).fill(170)];
  const level = splitLevel(grey);
  expect(level).toBeGreaterThanOrEqual(170);
  expect(level).toBeLessThan(255);
});
