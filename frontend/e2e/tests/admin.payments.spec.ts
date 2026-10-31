import { expect, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// P2-T06 acceptance: a customer buys on credit, pays part, and the balance shows the rest. The sale is in
// Sardine (never Seiche: the partnership lot test counts its kilos) to Poissonnerie El Bahr (C-003).
test.use({ storageState: OWNER_STATE });

/** "1 234,500 DT" → 1234.5 */
function amountOf(text: string | null): number {
  return Number((text ?? "").replace(/[^\d,-]/g, "").replace(",", "."));
}

async function choose(page: Page, scope: Page | ReturnType<Page["getByRole"]>, label: string, option: string) {
  await scope.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test("a customer pays part of a credit sale and the balance shows the rest", async ({ page }) => {
  test.slow();
  await page.goto("/ventes/nouvelle");
  await choose(page, page, "Client", "Poissonnerie El Bahr · C-003");
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Sardine · SA-010");
  await line.getByLabel("Poids (kg)").fill("2");
  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();
  await expect(page.getByText(/Brouillon VE-\d+ enregistré/)).toBeVisible();
  await page.getByRole("button", { name: "Valider la vente (BL)" }).click();
  await expect(page.getByText(/BL-\d{4}-\d+ validé/)).toBeVisible();

  await page.goto("/clients");
  await page.getByRole("searchbox").fill("El Bahr");
  await page.getByRole("link", { name: /Poissonnerie El Bahr/ }).click();
  const balance = page.getByTestId("customer-balance");
  await expect(balance).toBeVisible();
  const before = amountOf(await balance.textContent());
  expect(before).toBeGreaterThan(1);

  await page.getByRole("button", { name: "Enregistrer un règlement" }).click();
  await page.getByLabel("Montant (DT)").fill("1,000");
  await page.getByLabel("Référence (virement, carte…)").fill("CH-E2E");
  await page.getByRole("button", { name: "Enregistrer le règlement" }).click();
  await expect(page.getByText(/Règlement RG-\d+ enregistré/)).toBeVisible();

  await expect.poll(async () => amountOf(await balance.textContent())).toBeCloseTo(before - 1, 3);
  await expect(page.getByRole("cell", { name: /^Règlement RG-\d+/ }).first()).toBeVisible();

  await page.goto("/reglements");
  await expect(page.getByRole("heading", { name: "Règlements clients", level: 1 })).toBeVisible();
  await expect(page.getByRole("row", { name: /CH-E2E/ })).toContainText("Poissonnerie El Bahr");
});

test("the finance settings offer the credit limit policy", async ({ page }) => {
  await page.goto("/factures/parametres");
  await expect(page.getByLabel("Au-delà de la limite de crédit d'un client")).toContainText("Bloquer la vente");
});
