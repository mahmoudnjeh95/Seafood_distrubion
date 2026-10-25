import { expect, type Page, test } from "@playwright/test";

// Design tokens from packages/ui/src/styles.css.
const ICE = "rgb(238, 244, 247)";
const DEEP_WATER = "rgb(7, 26, 35)";

async function logIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("owner");
  await page.getByLabel("Mot de passe").fill("frutti-dev");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
}

const background = (page: Page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor);

test("the sidebar lists the modules of the prototype, plus the catalogue, and opens them", async ({ page }) => {
  await logIn(page);
  const modules = page.getByRole("navigation", { name: "Modules" });

  await expect(modules.getByRole("link")).toHaveText([
    "Tableau de bord",
    "Rapports",
    "Devis",
    "Ventes & factures",
    "Factures",
    "Règlements",
    "Clients",
    "Prix du jour",
    "Stock frigo & camions",
    "Camions du jour",
    "Journées chauffeurs",
    "Produits",
    "Achats",
    "Fournisseurs",
    "Documents",
    "Charges",
    "Personnel & salaires",
    "Partage des bénéfices",
    "Clôture mensuelle",
    "Demandes du site",
    "Produits du site",
    "Paramètres du site",
    "Import de données",
    "Paramètres",
  ]);
  await expect(modules.getByRole("link", { name: "Tableau de bord" })).toHaveAttribute("aria-current", "page");

  await modules.getByRole("link", { name: "Clients", exact: true }).click();

  await expect(page).toHaveURL(/\/clients$/);
  await expect(page.getByRole("heading", { name: "Clients", level: 1 })).toBeVisible();
  await expect(modules.getByRole("link", { name: "Clients", exact: true })).toHaveAttribute("aria-current", "page");
});

test("the theme switch changes the whole page and is remembered", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: "light" });
  await logIn(page);
  expect(await background(page)).toBe(ICE);
  await page.screenshot({ path: testInfo.outputPath("admin-light.png") });

  await page.getByRole("button", { name: "Thème sombre" }).click();

  expect(await background(page)).toBe(DEEP_WATER);
  await page.screenshot({ path: testInfo.outputPath("admin-dark.png") });

  await page.reload();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  expect(await background(page)).toBe(DEEP_WATER);

  await page.getByRole("button", { name: "Thème clair" }).click();
  expect(await background(page)).toBe(ICE);
});

test("with no choice made, the page follows the device theme", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/login");

  await expect(page.getByRole("form", { name: "Connexion" })).toBeVisible();
  expect(await background(page)).toBe(DEEP_WATER);
  await page.screenshot({ path: testInfo.outputPath("login-dark.png") });
});
