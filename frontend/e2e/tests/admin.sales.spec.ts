import { expect, type Locator, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// The demo sales come from `manage.py seed_dev` (D-051). These tests make their own sales from the fresh
// cold room, in products the other tests leave alone (rouget, sardine, poulpe), so they can run in any order.
test.use({ storageState: OWNER_STATE });

// In the grid a sale is typed in, the cell after the price and the discount: the kilos in stock.
const STOCK_CELL = 5;

async function choose(page: Page, scope: Page | Locator, label: string, option: string) {
  await scope.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test("the demo sales are listed with what is still owed", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Bons de livraison" }).click();
  await expect(page.getByRole("heading", { name: "Ventes", level: 1 })).toBeVisible();

  await page.getByRole("searchbox").fill("Corail");
  const row = page.getByRole("row", { name: /Restaurant Le Corail/ });
  await expect(row).toContainText("Confirmée");

  await row.getByRole("link").click();
  await expect(page.getByRole("heading", { name: /^BL-\d{4}-\d+$/, level: 1 })).toBeVisible();
  await expect(page.getByText(/Espèces · 50,000\sDT/)).toBeVisible();
  // Each line names the lots its kilos came from, with their cost.
  await expect(page.getByRole("list", { name: "Lots" }).first()).toContainText(/Lot L-\d+/);
});

test("a counter sale to the walk-in customer is weighed and confirmed at once, its payment left to the treasurer", async ({
  page,
}) => {
  test.slow();
  await page.goto("/ventes");
  await page.getByRole("button", { name: "Vente comptoir" }).click();
  await expect(page.getByRole("heading", { name: "Vente comptoir", level: 1 })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Client" })).toHaveText("Client de passage");

  // The basket is a grid: its first row waits for a product, with the cursor in it.
  const basket = page.getByRole("region", { name: "Panier" });
  const line = basket.getByRole("row", { name: "Ligne 1", exact: true });
  await expect(line.getByRole("combobox", { name: "Produit" })).toBeFocused();
  await choose(page, line, "Produit", "Rouget · RO-009");
  // The daily price is proposed; the cold room's stock is shown; the oldest lot goes first unless one is picked.
  await expect(line.getByLabel("Prix (DT/kg)")).toHaveValue("14,000");
  // No discount column at the counter: the stock is one cell earlier than on the sale form (the lot is last, D-201).
  await expect(line.getByRole("cell").nth(STOCK_CELL - 1)).toHaveText(/^[\d\s,]+kg$/);
  await expect(line.getByRole("button", { name: "Lot" })).toHaveText("Lot le plus ancien (FIFO)");
  await line.getByLabel("Poids (kg)").fill("1,5");
  await expect(line).toContainText(/21,000\sDT/);

  await page.getByRole("button", { name: /Enregistrer la vente \(21,000\sDT\)/ }).click();

  await expect(page.getByRole("status")).toContainText(/Vente BL-\d{4}-\d+ enregistrée/);
  // A new basket is ready for the next customer.
  await expect(line.getByRole("combobox", { name: "Produit" })).toHaveValue("");
  await expect(page.getByRole("button", { name: /Enregistrer la vente \(0,000\sDT\)/ })).toBeDisabled();
  await page.getByRole("link", { name: "Voir la vente" }).click();

  await expect(page.getByText("Confirmée", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Client de passage" })).toBeVisible();
  // Nothing was paid at the counter: the money is the treasurer's, so the sale still owes all of it.
  await expect(page.getByRole("region", { name: /^Vente BL-/ })).toContainText(/Reste dû\s*21,000\sDT/);
  await expect(page.getByRole("link", { name: "Encaisser au trésorier" })).toBeVisible();
});

test("a sale is drafted, confirmed, shows on its lot, then is cancelled with a reason", async ({ page }) => {
  test.slow();
  await page.goto("/ventes/nouvelle");
  await choose(page, page, "Client", "Poissonnerie El Bahr · C-003");
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Sardine · SA-010");
  await expect(line.getByLabel("Prix (DT/kg)")).toHaveValue("7,500");
  await line.getByLabel("Poids (kg)").fill("4");
  // 4 × 7.500
  await expect(line).toContainText(/30,000\sDT/);
  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();

  await expect(page.getByText(/Brouillon VE-\d+ enregistré/)).toBeVisible();
  await expect(page.getByRole("note")).toContainText("rien n'est encore sorti du stock");

  // Validating the draft makes it the delivery note: VE-0007 becomes BL-2026-0007 (D-095).
  await page.getByRole("button", { name: "Valider la vente (BL)" }).click();
  // The page shows the draft number until the sale is read again: wait for the BL number.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^BL-\d{4}-\d+$/);
  const number = (await page.getByRole("heading", { level: 1 }).textContent()) ?? "";
  await expect(page.getByRole("region", { name: /^Vente BL-/ })).toContainText(/Reste dû\s*30,000\sDT/);

  // Drill down to the lot the kilos came from: its sales list this one.
  await page.getByRole("list", { name: "Lots" }).getByRole("link").first().click();
  const lotSales = page.getByRole("region", { name: "Ventes de ce lot" });
  await expect(page.getByRole("heading", { name: "Ventes de ce lot" })).toBeVisible();
  await expect(lotSales.getByRole("link", { name: number })).toBeVisible();
  await lotSales.getByRole("link", { name: number }).click();

  await page.getByRole("button", { name: "Annuler la vente" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("reviennent dans les mêmes lots");
  await dialog.getByRole("button", { name: "Annuler la vente" }).click();
  await expect(dialog.getByText("Indiquez la raison de l'annulation.")).toBeVisible();
  await dialog.getByLabel("Motif").fill("Commande annulée par téléphone");
  await dialog.getByRole("button", { name: "Annuler la vente" }).click();

  await expect(page.getByText(new RegExp(`Vente ${number} annulée`))).toBeVisible();
  await expect(page.getByText("Annulée", { exact: true })).toBeVisible();
  await expect(page.getByText("Commande annulée par téléphone")).toBeVisible();
});

test("a sale's rows are typed from the keyboard like a spreadsheet, the product found by its code", async ({
  page,
}) => {
  await page.goto("/ventes/nouvelle");
  await choose(page, page, "Client", "Poissonnerie El Bahr · C-003");
  const row = (number: number) => page.getByRole("row", { name: `Ligne ${number}`, exact: true });
  const product = (number: number) => row(number).getByRole("combobox", { name: "Produit" });

  // A code typed without its dash finds the product; Enter takes it and goes to the kilos.
  await product(1).click();
  await page.keyboard.type("sa010");
  await expect(page.getByRole("option")).toHaveText([/^SardineSA-010/]);
  await page.keyboard.press("Enter");
  await expect(product(1)).toHaveValue("Sardine · SA-010");
  await expect(row(1).getByLabel("Poids (kg)")).toBeFocused();
  await expect(page.getByText(/Prix en vigueur : 7,500\sDT/)).toBeVisible();
  await expect(row(1).getByRole("cell").nth(STOCK_CELL)).toHaveText(/^[\d\s,]+kg$/);

  // Enter walks the row cell by cell, then starts the next row, which is already there.
  await page.keyboard.type("4");
  await page.keyboard.press("Enter");
  await expect(row(1).getByLabel("Prix (DT/kg)")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(row(1).getByLabel("Remise (%)")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(product(2)).toBeFocused();

  // A name, or a part of it, finds the product too; the price typed replaces the one proposed.
  await page.keyboard.type("poul");
  await page.keyboard.press("Enter");
  await expect(product(2)).toHaveValue("Poulpe · PO-006");
  await page.keyboard.type("2");
  await page.keyboard.press("Enter");
  await page.keyboard.type("30");
  // 4 × 7.500 + 2 × 30.000
  await expect(page.getByText(/Total HT\s*90,000\sDT/)).toBeVisible();

  // The arrows move between the rows; the same product on two rows is said at once.
  await page.keyboard.press("ArrowUp");
  await expect(row(1).getByLabel("Prix (DT/kg)")).toBeFocused();
  await product(3).click();
  await page.keyboard.type("sardine");
  await page.keyboard.press("Enter");
  await expect(row(3)).toContainText("Ce produit est déjà sur une autre ligne.");

  // Ctrl + Delete removes the row the cursor is in.
  await page.keyboard.press("Control+Delete");
  await expect(product(3)).toHaveValue("");
  await expect(row(4)).toHaveCount(0);
  await expect(page.getByText(/Total HT\s*90,000\sDT/)).toBeVisible();
});

test("a sale asking more than the cold room holds is refused under its line", async ({ page }) => {
  await page.goto("/ventes/nouvelle");
  await choose(page, page, "Client", "Client de passage");
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Poulpe · PO-006");
  await line.getByLabel("Poids (kg)").fill("5000");

  await page.getByRole("button", { name: "Enregistrer et confirmer" }).click();

  // No place holds 5 000 kg: the sale names the products and asks for two sales.
  await expect(page.getByText(/Aucun lieu ne contient tout ce poids \(Poulpe\)/)).toBeVisible();
  await expect(page).toHaveURL(/\/ventes\/nouvelle$/);
});

test("an accepted quote is converted into a sale and the two link to each other", async ({ page }) => {
  test.slow();
  await page.goto("/devis/nouveau");
  await choose(page, page, "Client", "Traiteur Les Saveurs · C-008");
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Poulpe · PO-006");
  await line.getByLabel("Poids (kg)").fill("2");
  await line.getByLabel("Prix (DT/kg)").fill("30");
  await page.getByRole("button", { name: "Enregistrer et envoyer" }).click();
  await expect(page.getByText(/Devis DV-\d{4}-\d+ enregistré et envoyé/)).toBeVisible();
  await page.getByRole("button", { name: "Marquer comme accepté" }).click();
  await expect(page.getByText(/Devis DV-\d{4}-\d+ accepté/)).toBeVisible();
  const quoteNumber = (await page.getByRole("heading", { level: 1 }).textContent()) ?? "";

  await page.getByRole("button", { name: "Convertir en vente" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).not.toContainText("Depuis");
  await dialog.getByRole("button", { name: "Créer et confirmer" }).click();

  await expect(page.getByText(/Vente BL-\d{4}-\d+ créée depuis le devis/)).toBeVisible();
  await expect(page.getByText("Confirmée", { exact: true })).toBeVisible();
  // The quote's price is kept: 2 × 30.000.
  await expect(page.getByRole("row", { name: /Poulpe/ })).toContainText(/60,000\sDT/);
  await page.getByRole("link", { name: quoteNumber }).click();

  await expect(page.getByText("Accepté", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /^BL-\d{4}-\d+$/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Convertir en vente" })).toHaveCount(0);
});

test("a quote is delivered in two BL: the first one takes part of it", async ({ page }) => {
  test.slow();
  await page.goto("/devis/nouveau");
  await choose(page, page, "Client", "Traiteur Les Saveurs · C-008");
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Poulpe · PO-006");
  await line.getByLabel("Poids (kg)").fill("2");
  await line.getByLabel("Prix (DT/kg)").fill("30");
  await page.getByRole("button", { name: "Enregistrer et envoyer" }).click();
  await expect(page.getByText(/Devis DV-\d{4}-\d+ enregistré et envoyé/)).toBeVisible();
  await page.getByRole("button", { name: "Marquer comme accepté" }).click();
  await expect(page.getByText(/Devis DV-\d{4}-\d+ accepté/)).toBeVisible();
  const quoteNumber = (await page.getByRole("heading", { level: 1 }).textContent()) ?? "";

  // The dialog proposes the 2 kg; half a kilo goes on a first BL, kept as a draft.
  await page.getByRole("button", { name: "Convertir en vente" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("À livrer (kg) · Poulpe")).toHaveValue("2");
  await dialog.getByLabel("À livrer (kg) · Poulpe").fill("0,5");
  await dialog.getByRole("button", { name: "Créer le brouillon" }).click();

  await expect(page.getByText(/Vente VE-\d+ créée depuis le devis/)).toBeVisible();
  await expect(page.getByRole("row", { name: /Poulpe/ })).toContainText(/15,000\sDT/);
  await page.getByRole("link", { name: quoteNumber }).click();

  // The quote still has 1.5 kg to deliver, so it can become another BL.
  await expect(page.getByText(/Reste à livrer : 1,500\skg/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Convertir en vente" })).toBeVisible();
});
