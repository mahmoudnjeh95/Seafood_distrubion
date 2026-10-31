import { expect, test } from "@playwright/test";

// Logins created by `manage.py seed_dev`.
const PASSWORD = "frutti-dev";

test("the driver logs in to the driver app and logs out", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Identifiant").fill("driver");
  await page.getByLabel("Mot de passe").fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();

  await expect(page.getByRole("heading", { name: "Bonjour Sami" })).toBeVisible();
  // The demo driver drives Camion 1: the session says so (`/me`).
  // The name shows twice (header eyebrow and the truck card in <main>), so check the card.
  await expect(page.getByRole("main").getByText("Camion 1", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Navigation camion" })).toBeVisible();

  await page.getByRole("button", { name: "Se déconnecter" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Se déconnecter" }).click();
  await expect(page.getByRole("form", { name: "Connexion" })).toBeVisible();
});

test("the driver app turns the owner away", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel("Identifiant").fill("owner");
  await page.getByLabel("Mot de passe").fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();

  await expect(page.getByRole("alert")).toContainText("pas un compte chauffeur");
  await expect(page.getByRole("navigation", { name: "Navigation camion" })).toHaveCount(0);
});
