import { expect, type Locator, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// Camion 2's demo day (morning load and evening return) comes from `manage.py seed_dev`. These tests load
// and unload Camion 3 only, so the demo day never changes.
test.use({ storageState: OWNER_STATE });

const COLD_ROOMS = "Chambres froides (toutes)";

async function openTransfers(page: Page) {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Modules" }).getByRole("link", { name: "Transferts" }).click();
  await expect(page.getByRole("heading", { name: "Transferts", level: 1 })).toBeVisible();
}

async function choose(page: Page, scope: Page | Locator, label: string, option: string) {
  await scope.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test("the evening return of the demo truck shows loaded − returned = sold or lost", async ({ page }) => {
  await openTransfers(page);
  await page.getByRole("group", { name: "Type de transfert" }).getByRole("button", { name: "Retour" }).click();
  await page.getByRole("searchbox").fill("Camion 2");
  // Wait for the search to apply: the list re-renders under the pointer otherwise.
  await expect(page.getByText("1 transfert", { exact: true })).toBeVisible();

  await page
    .getByRole("row", { name: /Camion 2 → Chambre froide 1/ })
    .getByRole("link")
    .first()
    .click();

  await expect(page.getByRole("heading", { name: /^TR-\d+$/, level: 1 })).toBeVisible();
  await expect(page.getByText("Validé", { exact: true })).toBeVisible();
  const day = page.getByRole("region", { name: /Journée de Camion 2/ });
  await expect(day).toContainText("Chargé − retourné = vendu ou perdu");
  const dorade = day.getByRole("row", { name: /Dorade royale/ });
  await expect(dorade).toContainText(/10,000\skg/);
  await expect(dorade).toContainText(/2,500\skg/);
  await expect(dorade).toContainText(/7,500\skg/);
  await expect(dorade).toContainText(/25,000\sDT/);
});

test("the owner loads Camion 3 at the day's price, from the cold rooms together", async ({ page }) => {
  test.slow(); // a transfer filled and validated through the screens
  await openTransfers(page);
  await page.getByRole("button", { name: "Nouveau transfert" }).click();
  await expect(page.getByRole("heading", { name: "Nouveau transfert", level: 1 })).toBeVisible();

  // No cold room to pick: the products say where they are (D-174).
  await choose(page, page, "Départ", COLD_ROOMS);
  await choose(page, page, "Arrivée", "Camion 3");
  await expect(page.getByText("Chargement du camion")).toBeVisible();
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Loup de mer · LO-004");
  // The price in force is proposed; the owner sells a little dearer today.
  await expect(line.getByLabel("Prix (DT/kg)")).toHaveValue("27,000");
  await line.getByLabel("Poids (kg)").fill("2");
  await line.getByLabel("Prix (DT/kg)").fill("28");
  await expect(line).toContainText(/56,000\sDT/);
  await page.getByRole("button", { name: "Valider le transfert" }).click();

  await expect(page.getByText(/Transfert TR-\d+ validé/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /^TR-\d+$/, level: 1 })).toBeVisible();
  await expect(page.getByText("Chambres froides", { exact: true }).first()).toBeVisible();
  const loaded = page.getByRole("row", { name: /Loup de mer/ }).first();
  await expect(loaded).toContainText(/28,000\sDT/);
  await expect(loaded).toContainText(/L-\d+ · 2,000\skg/);
  await expect(page.getByRole("region", { name: /Journée de Camion 3/ })).toContainText("Loup de mer");
});

test("a load for a client gets the client's own BL, at the address typed for it, ready to print", async ({ page }) => {
  test.slow();
  await page.goto("/stock/transferts/nouveau");
  await choose(page, page, "Arrivée", "Camion 3");
  await page.getByRole("button", { name: "Ajouter un client" }).click();
  const client = page.getByRole("group", { name: "Client 1" });
  await choose(page, client, "Client", "Hôtel Thyna · C-002");
  await client.getByLabel("Adresse de livraison").fill("Quai 3, port de Sfax");
  const line = client.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Loup de mer · LO-004");
  await line.getByLabel("Poids (kg)").fill("1");
  await page.getByRole("button", { name: "Valider le transfert" }).click();

  await expect(page.getByText(/Transfert TR-\d+ validé/)).toBeVisible();
  const notes = page.getByRole("region", { name: "Bons de livraison par client" });
  await expect(notes).toContainText("Hôtel Thyna");
  await expect(notes).toContainText("Quai 3, port de Sfax");
  await expect(page.getByRole("button", { name: "Tout imprimer" })).toBeVisible();
});

test("a load bigger than the cold rooms' stock is refused on its line and nothing is saved", async ({ page }) => {
  await page.goto("/stock/transferts/nouveau");
  await choose(page, page, "Arrivée", "Camion 3");
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Dorade royale · DO-003");
  await line.getByLabel("Poids (kg)").fill("99999");

  await page.getByRole("button", { name: "Valider le transfert" }).click();

  await expect(line.getByText(/Stock insuffisant/)).toBeVisible();
  await expect(page).toHaveURL(/\/stock\/transferts\/nouveau$/);
});

test("a draft load is saved, changed, then cancelled without moving stock", async ({ page }) => {
  await page.goto("/stock/transferts/nouveau");
  await choose(page, page, "Arrivée", "Camion 3");
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Loup de mer · LO-004");
  await line.getByLabel("Poids (kg)").fill("1");
  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();

  await expect(page.getByText(/Brouillon TR-\d+ enregistré/)).toBeVisible();
  await expect(page.getByRole("note")).toContainText("rien n'a encore bougé");

  await page.getByRole("button", { name: "Modifier" }).click();
  await page.getByRole("row", { name: "Ligne 1", exact: true }).getByLabel("Poids (kg)").fill("2,5");
  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();
  await expect(page.getByRole("row", { name: /Loup de mer/ }).first()).toContainText(/2,500\skg/);

  await page.getByRole("button", { name: "Annuler le brouillon" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Annuler le brouillon" }).click();

  await expect(page.getByText(/Brouillon TR-\d+ annulé/)).toBeVisible();
  await expect(page.getByText("Annulé", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Modifier" })).toHaveCount(0);
});
