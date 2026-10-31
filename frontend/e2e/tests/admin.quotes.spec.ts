import { expect, type Locator, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// The demo quotes come from `manage.py seed_dev`; DV-0001 is the prototype's quote to Restaurant Le Corail.
// These tests make their own quotes for Hôtel Thyna and Traiteur Les Saveurs, so the demo ones never change.
test.use({ storageState: OWNER_STATE });

async function choose(page: Page, scope: Page | Locator, label: string, option: string) {
  await scope.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test("the demo quote to Restaurant Le Corail reads like the prototype", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Devis", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Devis", level: 1 })).toBeVisible();
  await page.getByRole("searchbox").fill("Corail");
  await expect(page.getByText("1 devis", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: /^DV-\d{4}-0001$/ }).click();

  const quote = page.getByRole("article", { name: /^Devis DV-\d{4}-0001$/ });
  await expect(quote).toContainText("Restaurant Le Corail");
  const crevette = quote.getByRole("row", { name: /Crevette Royale/ });
  await expect(crevette).toContainText(/5,000\skg/);
  await expect(crevette).toContainText(/42,000\sDT/);
  await expect(crevette).toContainText(/210,000\sDT/);
  await expect(quote).toContainText(/Total HT\s*379,500\sDT/);
  await expect(quote).toContainText("avec la facturation");
});

test("the owner quotes a hotel with a discount, sends it, and records the yes", async ({ page }) => {
  test.slow(); // the form, then two actions on the quote page
  await page.goto("/devis");
  await page.getByRole("button", { name: "Nouveau devis" }).click();
  await expect(page.getByRole("heading", { name: "Nouveau devis", level: 1 })).toBeVisible();

  await choose(page, page, "Client", "Hôtel Thyna · C-002");
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Dorade royale · DO-003");
  // The hotel's own price list is proposed (D-049), and the stock of the chosen cold room is shown for
  // information.
  await expect(line.getByLabel("Prix (DT/kg)")).toHaveValue("22,500");
  await expect(page.getByText(/Prix du client \(Hôtel Thyna\) : 22,500\sDT/)).toBeVisible();
  // The cell after the discount: the kilos in stock at the cold room.
  await expect(line.getByRole("cell").nth(5)).toHaveText(/^[\d\s,]+kg$/);
  await line.getByLabel("Poids (kg)").fill("4");
  await line.getByLabel("Remise (%)").fill("10");
  // 4 × 22.500 = 90.000, less 10 % = 81.000
  await expect(line).toContainText(/81,000\sDT/);
  await page.getByRole("button", { name: "Enregistrer et envoyer" }).click();

  await expect(page.getByText(/Devis DV-\d{4}-\d+ enregistré et envoyé/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /^DV-\d{4}-\d+$/, level: 1 })).toBeVisible();
  await expect(page.getByText("Envoyé", { exact: true })).toBeVisible();
  const quote = page.getByRole("article", { name: /Devis DV-\d{4}-\d+/ });
  await expect(quote.getByRole("row", { name: /Dorade royale/ })).toContainText(/10\s%/);
  await expect(quote).toContainText(/Remises\s*−9,000\sDT/);
  await expect(page.getByRole("button", { name: "Modifier" })).toHaveCount(0);

  await page.getByRole("button", { name: "Marquer comme accepté" }).click();

  await expect(page.getByText(/Devis DV-\d{4}-\d+ accepté/)).toBeVisible();
  await expect(page.getByRole("note")).toContainText("Convertir en vente");
  await expect(page.getByRole("button", { name: "Marquer comme accepté" })).toHaveCount(0);
});

test("a draft is saved, changed, sent, then refused with a reason", async ({ page }) => {
  test.slow();
  await page.goto("/devis/nouveau");
  await choose(page, page, "Client", "Traiteur Les Saveurs · C-008");
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Calamar · CA-005");
  await line.getByLabel("Poids (kg)").fill("3");
  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();

  await expect(page.getByText(/Brouillon DV-\d{4}-\d+ enregistré/)).toBeVisible();
  await expect(page.getByRole("note")).toContainText("le client ne l'a pas encore");

  await page.getByRole("button", { name: "Modifier" }).click();
  await page.getByRole("row", { name: "Ligne 1", exact: true }).getByLabel("Poids (kg)").fill("2,5");
  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();
  // 2.5 × 29.000
  await expect(page.getByRole("row", { name: /Calamar/ })).toContainText(/72,500\sDT/);

  await page.getByRole("button", { name: "Marquer comme envoyé" }).click();
  await expect(page.getByText(/Devis DV-\d{4}-\d+ marqué comme envoyé/)).toBeVisible();
  await page.getByRole("button", { name: "Marquer comme refusé" }).click();
  await page.getByRole("dialog").getByLabel("Motif (facultatif)").fill("Trop cher cette semaine");
  await page.getByRole("dialog").getByRole("button", { name: "Enregistrer le refus" }).click();

  await expect(page.getByText(/Devis DV-\d{4}-\d+ refusé/)).toBeVisible();
  await expect(page.getByText("Trop cher cette semaine")).toBeVisible();
});

test("a discount the server refuses shows under its own line", async ({ page }) => {
  await page.goto("/devis/nouveau");
  await choose(page, page, "Client", "Hôtel Thyna · C-002");
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Calamar · CA-005");
  await line.getByLabel("Poids (kg)").fill("1");
  await line.getByLabel("Remise (%)").fill("150");

  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();

  await expect(line.getByText(/Indiquez une remise en %/)).toBeVisible();
  await expect(page).toHaveURL(/\/devis\/nouveau$/);
});
