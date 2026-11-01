import { expect, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// The demo invoice (MPS-F-2026-118 for receipt BR-0001, 1 471,500 DT, 500,000 DT paid by cheque) comes
// from `manage.py seed_dev`.
test.use({ storageState: OWNER_STATE });

async function openInvoices(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Achats" }).click();
  await page.getByRole("navigation", { name: "Achats" }).getByRole("link", { name: "Factures" }).click();
  await expect(page.getByRole("heading", { name: "Factures fournisseurs", level: 1 })).toBeVisible();
}

/** Record a receipt from Aqua Monastir through the form; returns its number (BR-…). */
async function recordReceipt(page: Page, deliveryNote: string): Promise<string> {
  await page.goto("/achats/nouvelle");
  await page.getByRole("combobox", { name: "Fournisseur" }).click();
  await page.getByRole("option", { name: "Aqua Monastir" }).click();
  await page.getByLabel("N° du bon de livraison ou de la facture").fill(deliveryNote);
  const line = page.getByRole("row").nth(1);
  await line.getByRole("combobox", { name: "Produit" }).click();
  // Not loup de mer: the receipts test expects the demo's last cost for it.
  await page.getByRole("option", { name: "Dorade royale · DO-003" }).click();
  await line.getByLabel("Facturé (kg)").fill("10");
  await line.getByLabel("Coût (DT/kg)").fill("20");
  // This receipt waits for the supplier's invoice, typed below (not owed at once, D-159).
  await page.getByRole("checkbox", { name: "Dû dès la réception" }).uncheck();
  await page.getByRole("button", { name: "Enregistrer la réception" }).click();
  const heading = page.getByRole("heading", { name: /^BR-\d+$/, level: 1 });
  await expect(heading).toBeVisible();
  return (await heading.textContent()) ?? "";
}

test("the demo invoice is partly paid and the supplier page shows what is still owed", async ({ page }) => {
  await openInvoices(page);
  await page.getByRole("searchbox").fill("MPS-F-2026-118");

  await page
    .getByRole("row", { name: /MPS-F-2026-118/ })
    .getByRole("link", { name: /^FF-\d+$/ })
    .click();

  await expect(page.getByRole("heading", { name: /^FF-\d+$/, level: 1 })).toBeVisible();
  await expect(page.getByText("Payée en partie").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "BR-0001" })).toBeVisible();
  await expect(page.getByRole("row", { name: /RF-\d{4}-\d+/ })).toContainText(/Chèque · CH-0042117.*500,000\sDT/);
  await expect(page.getByText(/^971,500\sDT$/)).toBeVisible();

  await page.getByRole("link", { name: "Mareyeur Port de Sfax" }).click();
  await expect(page.getByRole("heading", { name: "Mareyeur Port de Sfax", level: 1 })).toBeVisible();
  await expect(page.getByText("Solde fournisseur")).toBeVisible();
  await expect(page.getByText("Total à régler")).toBeVisible();
  await expect(page.getByText(/^971,500\sDT$/).first()).toBeVisible();
  await expect(page.getByText(/soldes séparés/)).toBeVisible();
});

test("the owner invoices a receipt, posts it and pays it in full", async ({ page }) => {
  // The development database is kept between runs: a new delivery note and invoice number every time.
  const stamp = Date.now();
  const receipt = await recordReceipt(page, `AQM-${stamp}`);

  await openInvoices(page);
  await page.getByRole("button", { name: "Nouvelle facture" }).click();
  await expect(page.getByRole("heading", { name: "Nouvelle facture fournisseur", level: 1 })).toBeVisible();
  await page.getByRole("combobox", { name: "Fournisseur" }).click();
  await page.getByRole("option", { name: "Aqua Monastir" }).click();
  await page.getByRole("checkbox", { name: new RegExp(`^${receipt} du `) }).check();
  // 10 kg invoiced × 20 DT: the amount comes from the receipt, it is never typed.
  await expect(page.getByText("Montant de la facture", { exact: true }).locator("..")).toContainText(/200,000\sDT/);
  await page.getByLabel("N° de la facture chez le fournisseur").fill(`AQM-F-${stamp}`);

  await page.getByRole("button", { name: "Enregistrer et valider" }).click();

  await expect(page.getByText(/Facture FF-\d+ enregistrée et validée/)).toBeVisible();
  const invoiceHeading = page.getByRole("heading", { name: /^FF-\d+$/, level: 1 });
  await expect(invoiceHeading).toBeVisible();
  const invoice = (await invoiceHeading.textContent()) ?? "";
  await expect(page.getByText("Validée", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: receipt })).toBeVisible();

  await page.getByRole("button", { name: "Enregistrer un paiement" }).click();
  await expect(page.getByRole("heading", { name: "Nouveau paiement fournisseur", level: 1 })).toBeVisible();
  // Coming from the invoice, the payment is its outstanding amount, all of it on that invoice.
  await expect(page.getByLabel("Montant (DT), ligne 1")).toHaveValue("200,000");
  // Other tests leave invoices of this supplier to pay (receipts owed at once, D-159): this one is checked by number.
  await expect(page.getByRole("textbox", { name: `Montant affecté à ${invoice}`, exact: true })).toHaveValue("200,000");
  await page.getByRole("combobox", { name: "Mode, ligne 1" }).click();
  await page.getByRole("option", { name: "Espèces" }).click();
  await page.getByRole("button", { name: "Enregistrer le paiement" }).click();
  // The last look before money is recorded (D-179): the total and where it goes.
  const confirm = page.getByRole("dialog");
  await expect(confirm).toContainText(/Total payé\s*200,000\sDT/);
  await confirm.getByRole("button", { name: "Confirmer" }).click();

  await expect(page.getByText(/Paiement RF-\d{4}-\d+ enregistré/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /^FF-\d+$/, level: 1 })).toBeVisible();
  await expect(page.getByText("Payée", { exact: true })).toBeVisible();
});

test("a payment beyond what an invoice still owes is refused on its row", async ({ page }) => {
  await page.goto("/achats/paiements/nouveau");
  await page.getByRole("button", { name: "Enregistrer le paiement" }).click();
  await expect(page.getByText("Obligatoire.").first()).toBeVisible();

  await page.getByRole("combobox", { name: "Fournisseur" }).click();
  await page.getByRole("option", { name: "Mareyeur Port de Sfax" }).click();
  await page.getByLabel("Montant (DT), ligne 1").fill("5000");
  const demoRow = page.getByRole("row", { name: /MPS-F-2026-118/ });
  await demoRow.getByRole("textbox").fill("5000");

  await expect(demoRow).toContainText(/Au plus 971,500\sDT restent à payer sur cette facture/);
  await page.getByRole("button", { name: "Enregistrer le paiement" }).click();
  await expect(page).toHaveURL(/\/achats\/paiements\/nouveau$/);
});
