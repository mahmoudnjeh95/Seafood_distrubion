import { expect, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// Demo suppliers created by `manage.py seed_dev`.
test.use({ storageState: OWNER_STATE });

async function openSuppliers(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Fournisseurs", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Fournisseurs", level: 1 })).toBeVisible();
}

test("the owner sees the demo suppliers, searches them and opens one", async ({ page }) => {
  await openSuppliers(page);

  const row = page.getByRole("row").filter({ hasText: "Mareyeur Port de Sfax" });
  await expect(row).toContainText("F-002");
  await expect(row).toContainText("+216 74 000 102");

  await page.getByRole("searchbox", { name: "Rechercher par nom, ville, téléphone ou contact" }).fill("trabelsi");
  await expect(page.getByRole("row")).toHaveCount(2); // the header and one supplier

  await page.getByRole("link", { name: "Mareyeur Port de Sfax" }).click();
  await expect(page.getByRole("heading", { name: "Mareyeur Port de Sfax", level: 1 })).toBeVisible();
  await expect(page.getByText("0000002B/A/M/000")).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "Karim Trabelsi" })).toContainText("Gérant");
  await expect(page.getByRole("listitem")).toHaveCount(2);
});

test("the owner creates a supplier with a contact, edits it and archives it", async ({ page }) => {
  // The development database is kept between runs: a new name and tax ID every time.
  const stamp = Date.now();
  const name = `Pêcherie E2E ${stamp}`;
  const taxNumber = String(stamp % 10_000_000).padStart(7, "0");
  await openSuppliers(page);

  await page.getByRole("button", { name: "Nouveau fournisseur" }).click();
  const dialog = page.getByRole("dialog", { name: "Nouveau fournisseur" });
  await dialog.getByLabel("Nom", { exact: true }).fill(name);
  await dialog.getByLabel("Matricule fiscal").fill(`${taxNumber} a a m 000`);
  await dialog.getByLabel("Ville").fill("Mahdia");
  await dialog.getByRole("button", { name: "Ajouter un contact" }).click();
  await dialog.getByLabel("Nom du contact").fill("Mounir");
  await dialog.getByLabel("Fonction").fill("Patron pêcheur");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();

  // A new supplier opens on its own page, with the next free reference.
  await expect(page.getByText("Fournisseur créé.")).toBeVisible();
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();
  await expect(page.getByText(/^F-\d{3}$/)).toBeVisible();
  await expect(page.getByText(`${taxNumber}A/A/M/000`)).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "Mounir" })).toContainText("Patron pêcheur");

  await page.getByRole("button", { name: "Modifier" }).click();
  const edit = page.getByRole("dialog", { name: "Modifier le fournisseur" });
  await edit.getByLabel("Téléphone", { exact: true }).fill("+216 73 000 999");
  await edit.getByRole("button", { name: "Retirer ce contact" }).click();
  await edit.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByText("Modifications enregistrées.")).toBeVisible();
  await expect(page.getByRole("link", { name: "+216 73 000 999" })).toBeVisible();
  await expect(page.getByText("Aucun contact enregistré.")).toBeVisible();

  await page.getByRole("button", { name: "Archiver" }).click();
  await expect(page.getByText("Archivé", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Tous les fournisseurs" }).click();
  await expect(page.getByRole("link", { name })).toHaveCount(0);
  await page.getByRole("button", { name: "Archivés" }).click();
  await expect(page.getByRole("row").filter({ hasText: name })).toContainText("Archivé");
});

test("a tax ID of the wrong shape is refused by the server on its field", async ({ page }) => {
  await openSuppliers(page);

  await page.getByRole("button", { name: "Nouveau fournisseur" }).click();
  const dialog = page.getByRole("dialog", { name: "Nouveau fournisseur" });
  await dialog.getByLabel("Nom", { exact: true }).fill("Doublon");
  await dialog.getByLabel("Matricule fiscal").fill("12AB");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();

  await expect(dialog.getByText(/Matricule fiscal invalide/)).toBeVisible();
});
