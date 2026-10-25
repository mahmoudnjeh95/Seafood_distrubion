import { expect, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// Demo customers created by `manage.py seed_dev`.
test.use({ storageState: OWNER_STATE });

async function openCustomers(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Clients", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Clients", level: 1 })).toBeVisible();
}

test("the owner sees the demo customers with their credit limit, searches and opens one", async ({ page }) => {
  await openCustomers(page);

  const row = page.getByRole("row").filter({ hasText: "Hôtel Thyna" });
  await expect(row).toContainText("C-002");
  await expect(row).toContainText(/5\s000,000\sDT/);
  await expect(row).toContainText("45 jours");

  await page.getByRole("searchbox", { name: "Rechercher par nom, ville, téléphone ou contact" }).fill("kammoun");
  await expect(page.getByRole("row")).toHaveCount(2); // the header and one customer

  await page.getByRole("link", { name: "Hôtel Thyna" }).click();
  await expect(page.getByRole("heading", { name: "Hôtel Thyna", level: 1 })).toBeVisible();
  await expect(page.getByText("0000102B/A/M/000")).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "Sonia Kammoun" })).toContainText("Économat");
});

test("the owner creates a customer with a credit limit, edits it and archives it", async ({ page }) => {
  // The development database is kept between runs: a new name and tax ID every time.
  const stamp = Date.now();
  const name = `Restaurant E2E ${stamp}`;
  const taxNumber = String(stamp % 10_000_000).padStart(7, "0");
  await openCustomers(page);

  await page.getByRole("button", { name: "Nouveau client" }).click();
  const dialog = page.getByRole("dialog", { name: "Nouveau client" });
  await dialog.getByLabel("Nom", { exact: true }).fill(name);
  await dialog.getByLabel("Matricule fiscal").fill(`${taxNumber} a a m 000`);
  await dialog.getByLabel("Limite de crédit (DT)").fill("1 250,5");
  await dialog.getByLabel("Délai de paiement (jours)").fill("30");
  await dialog.getByRole("button", { name: "Ajouter un contact" }).click();
  await dialog.getByLabel("Nom du contact").fill("Chef Mounir");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();

  // A new customer opens on its own page, with the next free reference.
  await expect(page.getByText("Client créé.")).toBeVisible();
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();
  await expect(page.getByText(/^C-\d{3}$/)).toBeVisible();
  await expect(page.getByText(`${taxNumber}A/A/M/000`)).toBeVisible();
  await expect(page.getByText(/1\s250,500\sDT/).first()).toBeVisible();
  await expect(page.getByText("30 jours", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Modifier" }).click();
  const edit = page.getByRole("dialog", { name: "Modifier le client" });
  await edit.getByLabel("Limite de crédit (DT)").fill("2000");
  await edit.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByText("Modifications enregistrées.")).toBeVisible();
  await expect(page.getByText(/2\s000,000\sDT/).first()).toBeVisible();

  await page.getByRole("button", { name: "Archiver" }).click();
  await expect(page.getByText("Archivé", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Tous les clients" }).click();
  await expect(page.getByRole("link", { name })).toHaveCount(0);
  await page.getByRole("button", { name: "Archivés" }).click();
  await expect(page.getByRole("row").filter({ hasText: name })).toContainText("Archivé");
});

test("a negative credit limit is refused and the walk-in customer cannot be archived", async ({ page }) => {
  await openCustomers(page);

  await page.getByRole("button", { name: "Nouveau client" }).click();
  const dialog = page.getByRole("dialog", { name: "Nouveau client" });
  await dialog.getByLabel("Nom", { exact: true }).fill("Doublon");
  await dialog.getByLabel("Limite de crédit (DT)").fill("-5");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(dialog.getByText("Montant invalide : 3 décimales au plus.")).toBeVisible();
  await dialog.getByRole("button", { name: "Annuler" }).click();

  await page.getByRole("link", { name: "Client de passage" }).click();
  await expect(page.getByRole("heading", { name: "Client de passage", level: 1 })).toBeVisible();
  await expect(page.getByRole("button", { name: "Archiver" })).toHaveCount(0);
});
