import { expect, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// Only reads: the page opens on the current month; the last finished month is picked here, and nothing is reviewed or approved here, so the
// other browser tests keep their data.
test.use({ storageState: OWNER_STATE });

test("the owner sees the last finished month with its result, its stock and its checks", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Clôture mensuelle", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Clôture mensuelle", level: 1 })).toBeVisible();

  const months = page.getByRole("group", { name: "Mois" });
  await expect(months.getByRole("button")).toHaveCount(12);

  const month = page.locator("section[aria-labelledby='month-title']");
  // The page opens on the current month, which cannot be closed before its last day.
  await expect(page.getByText("Ce mois n'est pas terminé")).toBeVisible();
  await expect(month.getByRole("button", { name: "Vérifier le mois" })).toHaveCount(0);

  // The month before is the last finished one.
  await months.getByRole("button").nth(1).click();
  await expect(month.getByText("Résultat net du mois")).toBeVisible();
  await expect(month.getByText("Stock à la fin du mois", { exact: true }).first()).toBeVisible();
  await expect(month.getByText("Toutes les dépenses du mois sont approuvées")).toBeVisible();
  console.log("DIAG-MONTH-START\n" + (await month.innerText()) + "\nDIAG-MONTH-END");
  await expect(month.getByRole("button", { name: "Vérifier le mois" })).toBeVisible();
  await expect(month.getByRole("button", { name: "Approuver et figer" })).toHaveCount(0);
});
