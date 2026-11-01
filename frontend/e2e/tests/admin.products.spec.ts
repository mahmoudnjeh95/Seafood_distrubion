import { expect, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// Demo catalogue created by `manage.py seed_dev`.
test.use({ storageState: OWNER_STATE });

// A 1 × 1 PNG: enough to go through the server's photo checks.
const PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function openCatalogue(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Produits", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Produits", level: 1 })).toBeVisible();
}

function card(page: Page, name: string) {
  return page.getByRole("article").filter({ has: page.getByRole("heading", { name, exact: true }) });
}

test("the owner sees the demo catalogue with today's prices and searches it", async ({ page }) => {
  await openCatalogue(page);

  const shrimp = card(page, "Crevette Royale");
  await expect(shrimp).toContainText("CR-001");
  await expect(shrimp).toContainText("42,000 DT / kg");
  await expect(shrimp).toContainText("0 à 4 °C");
  await expect(card(page, "Crevette décortiquée")).toContainText("≤ -18 °C");

  await page.getByRole("searchbox", { name: "Rechercher par nom ou référence" }).fill("dorade");
  await expect(page.getByRole("article")).toHaveCount(1);
  await expect(card(page, "Dorade royale")).toBeVisible();
});

test("the owner creates a product with a photo, changes its price and archives it", async ({ page }) => {
  // The development database is kept between runs: a new name every time. The reference is given by the server.
  const name = `Pageot E2E-${Date.now()}`;
  await openCatalogue(page);

  await page.getByRole("button", { name: "Nouveau produit" }).click();
  const dialog = page.getByRole("dialog", { name: "Nouveau produit" });
  await dialog.getByLabel("Nom (français)").fill(name);
  await dialog.getByLabel("Nom (arabe)").fill("باجو");
  await dialog.getByRole("combobox", { name: "Catégorie" }).click();
  await page.getByRole("option", { name: "Poissons" }).click();
  await dialog.getByLabel("Prix de vente (DT / kg)").fill("18,5");
  await dialog.getByLabel("Seuil d'alerte (kg)").fill("12");
  await dialog.getByLabel("Température max. (°C)").fill("4");
  await dialog.getByLabel("Température min. (°C)").fill("0");
  await dialog
    .locator('input[type="file"]')
    .setInputFiles({ name: "pageot.png", mimeType: "image/png", buffer: PIXEL_PNG });
  await dialog.getByRole("button", { name: "Enregistrer" }).click();

  await expect(page.getByText("Produit créé.")).toBeVisible();
  const created = card(page, name);
  await expect(created).toContainText("18,500 DT / kg");
  await expect(created).toContainText("Seuil 12,000 kg");
  await expect(created.locator("img")).toHaveAttribute("src", /\/api\/v1\/products\/\d+\/photo\?v=/);

  // A new price from now: the card follows, the old price stays in the history.
  await created.getByRole("button", { name }).click();
  const edit = page.getByRole("dialog", { name: "Modifier le produit" });
  await edit.getByLabel("Nouveau prix (DT / kg)").fill("16.5");
  await edit.getByRole("button", { name: "Appliquer maintenant" }).click();
  await expect(edit.getByRole("listitem")).toHaveCount(2);
  await expect(edit.getByRole("listitem").first()).toContainText("16,500 DT");
  await expect(edit.getByRole("listitem").first()).toContainText("En vigueur");
  // The page behind a dialog is hidden from assistive technology: close it to read the card.
  await edit.getByRole("button", { name: "Annuler" }).click();
  await expect(created).toContainText("16,500 DT / kg");

  await created.getByRole("button", { name }).click();
  await edit.getByRole("button", { name: "Archiver" }).click();
  await expect(created).toHaveCount(0);
  await page.getByRole("button", { name: "Archivés" }).click();
  await expect(card(page, name)).toContainText("Archivé");
});

test("a new product's reference is given by the numbering, not typed", async ({ page }) => {
  await openCatalogue(page);

  await page.getByRole("button", { name: "Nouveau produit" }).click();
  const dialog = page.getByRole("dialog", { name: "Nouveau produit" });
  await expect(dialog.getByLabel("Référence")).toBeDisabled();
  await expect(dialog.getByLabel("Référence")).toHaveAttribute("placeholder", "Automatique");
});
