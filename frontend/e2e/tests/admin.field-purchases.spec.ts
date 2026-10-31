import { expect, type Locator, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// Buying at the port (P3-T12a, D-176). The demo purchase from `manage.py seed_dev` waits to be checked; these tests type
// their own purchase of Moules from Surgelés du Sahel (no other test counts those kilos or that supplier's balance), then
// check it, save a revision and validate it.
test.use({ storageState: OWNER_STATE });

async function choose(page: Page, scope: Page | Locator, label: string, option: string) {
  await scope.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test("the demo purchase waits with the name the driver typed for a new product", async ({ page }) => {
  await page.goto("/achats/terrain");
  await expect(page.getByRole("heading", { name: "Achats terrain", level: 1 })).toBeVisible();
  await page.getByRole("searchbox").fill("KRK-0917");
  const row = page.getByRole("row", { name: /Pêcherie Kerkennah/ });
  await expect(row).toContainText("À valider");
  await row.getByRole("link", { name: /^AT-\d{4}-\d{4}$/ }).click();

  await expect(page.getByRole("heading", { name: /^Vérifier l'achat AT-/, level: 1 })).toBeVisible();
  await expect(page.getByText("Le chauffeur a écrit : « Pageot »")).toBeVisible();
  await expect(page.getByRole("button", { name: "Créer ce produit" })).toBeVisible();
  await expect(page.getByText("Première version, telle qu'envoyée.")).toBeVisible();
});

test("the office types a purchase, fixes the kilos received and validates it", async ({ page }) => {
  test.slow();
  await page.goto("/achats/terrain/nouveau");
  await expect(page.getByRole("heading", { name: "Saisir un achat terrain", level: 1 })).toBeVisible();
  await choose(page, page, "Fournisseur", "Surgelés du Sahel");
  await choose(page, page, "Accord de paiement", "À N jours");
  await page.getByLabel("Nombre de jours").fill("15");
  const line = page.getByRole("group", { name: "Produit 1", exact: true });
  await choose(page, line, "Produit", "Moules · MO-007");
  await line.getByLabel("Kilos du chauffeur").fill("10");
  await line.getByLabel("Prix (DT/kg)").fill("8,500");
  await page.getByRole("button", { name: "Ajouter un paiement" }).click();
  await page.getByRole("group", { name: "Paiement 1" }).getByLabel("Montant (DT)").fill("50");
  await page.getByRole("button", { name: "Enregistrer" }).click();

  await expect(page.getByRole("heading", { name: /^Vérifier l'achat AT-\d{4}-\d{4}$/, level: 1 })).toBeVisible();

  // The office counts 9.5 kg: 9.5 × 8.500 = 80.750 DT owed, 30.750 DT left after the 50 DT given.
  await page.getByRole("group", { name: "Produit 1", exact: true }).getByLabel("Kilos reçus").fill("9,5");
  await page.getByLabel("Note au chauffeur").fill("Pesé à 9,5 kg au froid.");
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByText(/version 2/)).toBeVisible();
  await expect(page.getByText("Produit 1 · kilos reçus : vide → 9,500 kg")).toBeVisible();
  await expect(page.getByText("« Pesé à 9,5 kg au froid. »")).toBeVisible();

  await page.getByRole("button", { name: "Valider l'achat" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("80,750");
  await dialog.getByRole("button", { name: "Valider l'achat" }).click();

  await expect(page.getByText(/validé : réception et paiements enregistrés/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /^AT-\d{4}-\d{4}$/, level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: /^BR-\d+$/ })).toBeVisible();
  // No invoice at validation (D-200): the office makes it from the receipt.
  await expect(page.getByRole("link", { name: "Facturer la réception" })).toBeVisible();
  await expect(page.getByText("30,750")).toBeVisible();
});
