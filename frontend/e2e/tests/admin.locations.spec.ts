import { expect, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// Demo cold rooms and trucks created by `manage.py seed_dev`; Camion 1 belongs to the demo driver Sami.
test.use({ storageState: OWNER_STATE });

async function openLocations(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Stock frigo & camions" }).click();
  await expect(page.getByRole("heading", { name: "Stock frigo & camions", level: 1 })).toBeVisible();
}

const place = (page: Page, name: string | RegExp) => page.getByRole("article", { name });

test("the owner sees the demo cold rooms and trucks with their drivers", async ({ page }) => {
  await openLocations(page);

  await expect(place(page, "Chambre froide 1 (frais)")).toContainText("Vente au comptoir");
  await expect(place(page, "Camion 1 · Sami B.")).toContainText("101 TU 2001");
  await expect(place(page, "Camion 2")).toContainText("Sans chauffeur aujourd'hui");
});

test("the owner adds a cold room and a truck, then archives the truck", async ({ page }) => {
  // The development database is kept between runs: new names and plates every time.
  const stamp = Date.now();
  const room = `Congélateur ${stamp}`;
  const truck = `Camion ${stamp}`;
  const plate = `${stamp % 1000} TU ${stamp % 10000}`;
  await openLocations(page);

  await page.getByRole("button", { name: "Nouvel emplacement" }).click();
  const roomDialog = page.getByRole("dialog", { name: "Nouvel emplacement" });
  await roomDialog.getByLabel("Nom").fill(room);
  await roomDialog.getByLabel("Les clients y achètent aussi au comptoir").uncheck();
  await roomDialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByText("Emplacement créé.")).toBeVisible();
  await expect(place(page, room)).toContainText("Chambre froide");
  await expect(place(page, room)).not.toContainText("Vente au comptoir");

  await page.getByRole("button", { name: "Nouveau camion" }).click();
  const truckDialog = page.getByRole("dialog", { name: "Nouveau camion" });
  await truckDialog.getByLabel("Nom").fill(truck);
  await truckDialog.getByLabel("Immatriculation").fill(plate.toLowerCase());
  await truckDialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByText("Camion créé.")).toBeVisible();
  await expect(place(page, truck)).toContainText(plate.toUpperCase());

  await place(page, truck).getByRole("button").first().click();
  const edit = page.getByRole("dialog", { name: "Modifier le camion" });
  await edit.getByRole("button", { name: "Archiver" }).click();
  await expect(place(page, truck)).toHaveCount(0);
  await page.getByRole("button", { name: "Archivés" }).click();
  await expect(place(page, truck)).toContainText("Archivé");
});

test("a cold room still holding stock cannot be archived", async ({ page }) => {
  // The demo seed received the demo batches into the cold rooms.
  await openLocations(page);

  await place(page, "Chambre froide 1 (frais)").getByRole("button").first().click();
  const edit = page.getByRole("dialog", { name: "Modifier l'emplacement" });
  await edit.getByRole("button", { name: "Archiver" }).click();
  await expect(edit.getByText(/contient encore du stock/)).toBeVisible();
});
