import { expect, test } from "vitest";

import { addTyped, chosenAddresses, setTicked, typedAddresses } from "./emailRecipients";

test("typed addresses split on commas, semicolons and spaces; one bad address refuses them all", () => {
  expect(typedAddresses("a@example.tn, b@example.tn;c@example.tn  d@example.tn")).toEqual([
    "a@example.tn",
    "b@example.tn",
    "c@example.tn",
    "d@example.tn",
  ]);
  expect(typedAddresses("a@example.tn, pas-une-adresse")).toBeNull();
  expect(typedAddresses("")).toEqual([]);
});

test("every ticked address is sent, unticked ones are left out for this send only", () => {
  const offered = ["corail@example.tn", "chef@example.tn", "compta@example.tn"];
  let unticked: string[] = [];
  unticked = setTicked(unticked, "chef@example.tn", false);
  expect(chosenAddresses(offered, unticked)).toEqual(["corail@example.tn", "compta@example.tn"]);
  unticked = setTicked(unticked, "CHEF@example.tn", true);
  expect(chosenAddresses(offered, unticked)).toEqual(offered);
});

test("an added address is offered once, whatever its case, and an unticked one is ticked back when typed again", () => {
  const offered = ["corail@example.tn", "chef@example.tn"];
  const first = addTyped([], offered, ["chef@example.tn"], ["Nouveau@example.tn", "nouveau@example.tn"]);
  expect(first.added).toEqual(["Nouveau@example.tn"]);
  expect(first.unticked).toEqual(["chef@example.tn"]);

  const again = addTyped([], offered, ["chef@example.tn"], ["CHEF@example.tn"]);
  expect(again.added).toEqual([]);
  expect(again.unticked).toEqual([]);
  expect(chosenAddresses(offered, again.unticked)).toEqual(offered);
});
