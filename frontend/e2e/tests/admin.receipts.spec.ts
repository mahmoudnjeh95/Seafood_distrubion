import { expect, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// The demo receipt BR-0001 and the demo batches come from `manage.py seed_dev`.
test.use({ storageState: OWNER_STATE });

async function openReceipts(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Achats" }).click();
  await expect(page.getByRole("heading", { name: "Réceptions fournisseurs", level: 1 })).toBeVisible();
}

test("the owner finds the demo receipt with its weight difference", async ({ page }) => {
  await openReceipts(page);
  await page.getByLabel("Avec écart de poids seulement").check();
  await page.getByRole("searchbox").fill("MPS-5544");

  await page.getByRole("link", { name: "BR-0001" }).click();

  await expect(page.getByRole("heading", { name: "BR-0001", level: 1 })).toBeVisible();
  const note = page.getByRole("note");
  await expect(note).toContainText("Écart de poids à la réception");
  await expect(note).toContainText(/Dorade royale L-\d+(?:-\d+)? : 60,000\skg acceptés pour 62,000\skg facturés/);
  await expect(page.getByText("Mareyeur Port de Sfax").first()).toBeVisible();
});

test("the owner records a receipt; the last cost is suggested and the change shown", async ({ page }) => {
  // The development database is kept between runs: a new delivery note every time.
  const deliveryNote = `AQM-${Date.now()}`;
  await openReceipts(page);
  await page.getByRole("button", { name: "Nouvelle réception" }).click();
  await expect(page.getByRole("heading", { name: "Nouvelle réception", level: 1 })).toBeVisible();

  await page.getByRole("combobox", { name: "Fournisseur" }).click();
  await page.getByRole("option", { name: "Aqua Monastir" }).click();
  await expect(page.getByRole("combobox", { name: "Reçu dans" })).toContainText("Chambre froide 1 (frais)");
  await page.getByLabel("N° du bon de livraison ou de la facture").fill(deliveryNote);

  const line = page.getByRole("row").nth(1);
  await line.getByRole("combobox", { name: "Produit" }).click();
  await page.getByRole("option", { name: "Loup de mer · LO-004" }).click();
  // Aqua Monastir last sold loup de mer at 21.500 DT/kg (demo batches).
  await expect(line.getByLabel("Coût (DT/kg)")).toHaveValue(/^21,5/);
  await expect(line).toContainText(/Dernier prix : 21,500\sDT le/);

  await line.getByLabel("Facturé (kg)").fill("18");
  await expect(line.getByLabel("Accepté (kg)")).toHaveValue("18");
  await line.getByLabel("Accepté (kg)").fill("17,5");
  await line.getByLabel("Coût (DT/kg)").fill("22");
  await expect(line).toContainText(/\(\+2,3\s%\)/);
  await expect(line).toContainText(/396,000\sDT/);

  await page.getByRole("button", { name: "Enregistrer la réception" }).click();

  await expect(page.getByText(/Réception BR-\d+ enregistrée/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /^BR-\d+$/, level: 1 })).toBeVisible();
  await expect(page.getByText(deliveryNote)).toBeVisible();
  await expect(page.getByRole("note")).toContainText(
    /Loup de mer L-\d+(?:-\d+)? : 17,500\skg acceptés pour 18,000\skg facturés/,
  );
});

test("a receipt without weights is refused on the line's own fields", async ({ page }) => {
  await page.goto("/achats/nouvelle");
  await page.getByRole("combobox", { name: "Fournisseur" }).click();
  await page.getByRole("option", { name: "Aqua Monastir" }).click();

  await page.getByRole("button", { name: "Enregistrer la réception" }).click();

  const line = page.getByRole("row").nth(1);
  await expect(line.getByText("Obligatoire.")).toBeVisible();
  await expect(line.getByText("Poids en kg, 3 décimales au plus.").first()).toBeVisible();
  await expect(page).toHaveURL(/\/achats\/nouvelle$/);
});
