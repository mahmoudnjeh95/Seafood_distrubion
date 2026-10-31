import { expect, test } from "@playwright/test";

// Logins created by `manage.py seed_dev`.
const PASSWORD = "frutti-dev";

test("the owner logs in to the admin app and logs out", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Identifiant").fill("owner");
  await page.getByLabel("Mot de passe").fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();

  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await expect(page.getByText("Propriétaire", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/$/);

  await page.getByRole("button", { name: "Se déconnecter" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Se déconnecter" }).click();
  await expect(page.getByRole("form", { name: "Connexion" })).toBeVisible();
});

test("a wrong password is refused with a clear message", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel("Identifiant").fill("owner");
  await page.getByLabel("Mot de passe").fill("not-the-password");
  await page.getByRole("button", { name: "Se connecter" }).click();

  await expect(page.getByRole("alert")).toHaveText("Identifiant ou mot de passe incorrect.");
  await expect(page).toHaveURL(/\/login$/);
});

test("the admin app turns a driver away", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel("Identifiant").fill("driver");
  await page.getByLabel("Mot de passe").fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();

  await expect(page.getByRole("alert")).toContainText("compte chauffeur");
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toHaveCount(0);
});
