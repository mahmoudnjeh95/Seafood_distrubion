import { expect, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// Demo data from `manage.py seed_dev`: last month's electricity bill (684,250 DT) typed and approved, the
// -20 degree room weighing 2; rent, accountant and a 12-month insurance generated for this month.
test.use({ storageState: OWNER_STATE });

test("cold-room cost shows the approved bill of last month, the room shares and an estimated month", async ({
  page,
}) => {
  test.slow();
  await page.goto("/charges/froid");
  await expect(page.getByRole("heading", { name: "Chambres froides : coût", level: 1 })).toBeVisible();

  const bill = page.getByRole("region", { name: /Facture chambre froide réelle de/ });
  await expect(bill).toContainText("Approuvée");
  await expect(bill).toContainText(/684,250\sDT/);

  const rooms = page.getByRole("region", { name: "Coût par chambre" });
  await expect(rooms.getByRole("row", { name: /Chambre froide 2 \(congelé\)/ })).toContainText("Réel");

  const shares = page.getByRole("region", { name: "Part de chaque chambre" });
  await expect(shares.getByLabel("Part de Chambre froide 2 (congelé) (%)")).toHaveValue(/^\d+,\d+$/);

  // The month after is estimated at last month's daily rate.
  await page.getByRole("button", { name: "Mois suivant" }).click();
  await expect(page.getByRole("region", { name: "Coût par chambre" })).toContainText("Estimé");
  await expect(page.getByText(/Estimation au tarif journalier de/)).toBeVisible();
});

test("general costs list the monthly templates and this month's generated costs", async ({ page }) => {
  test.slow();
  await page.goto("/charges");
  await page
    .getByRole("navigation", { name: "Rubriques des charges" })
    .getByRole("link", { name: "Frais généraux" })
    .click();
  await expect(page.getByRole("heading", { name: "Frais généraux", level: 1 })).toBeVisible();

  const recurring = page.getByRole("region", { name: "Frais mensuels" });
  await expect(recurring.getByRole("row", { name: /Loyer du dépôt/ })).toContainText(/1\s?200,000\sDT/);
  await expect(recurring.getByRole("row", { name: /Honoraires comptables/ })).toBeVisible();

  const month = page.getByRole("region", { name: /^Frais de / });
  await expect(month.getByRole("row", { name: /Assurance annuelle du dépôt/ })).toContainText("12 mois");
  await expect(month.getByRole("row", { name: /Loyer du dépôt/ })).toContainText("Approuvée");
});
