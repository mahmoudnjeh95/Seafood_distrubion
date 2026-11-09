import { expect, type Locator, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// The five Perfaxis gaps the owner kept on 2026-11-07 (D-285 to D-289). Each test makes its own records from the
// `seed_dev` demo data, in products the other tests leave alone where it matters.
test.use({ storageState: OWNER_STATE });

const PDF = Buffer.from("%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n");

async function choose(page: Page, scope: Page | Locator, label: string, option: string) {
  await scope.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

/** A new goods receipt of 10 kg of loup de mer from Aqua Monastir; ends on its page. */
async function newReceipt(page: Page): Promise<string> {
  await page.goto("/achats/nouvelle");
  await expect(page.getByRole("heading", { name: "Nouvelle réception", level: 1 })).toBeVisible();
  await choose(page, page, "Fournisseur", "Aqua Monastir");
  await page.getByLabel("N° du bon de livraison ou de la facture").fill(`E2E-${Date.now()}`);
  const line = page.getByRole("row").nth(1);
  await line.getByRole("combobox", { name: "Produit" }).click();
  await page.getByRole("option", { name: "Loup de mer · LO-004" }).click();
  await line.getByLabel("Facturé (kg)").fill("10");
  await line.getByLabel("Coût (DT/kg)").fill("20");
  await page.getByRole("button", { name: "Enregistrer la réception" }).click();
  await expect(page.getByRole("heading", { name: /^BR-\d+$/, level: 1 })).toBeVisible();
  return (await page.getByRole("heading", { level: 1 }).textContent()) ?? "";
}

/** A confirmed BL of 2 kg of sardine to Poissonnerie El Bahr, with the billing chosen; ends on its page. */
async function newBl(page: Page, billing: "Facturable" | "Non facturable" | "Offert"): Promise<void> {
  await page.goto("/ventes/nouvelle");
  await choose(page, page, "Client", "Poissonnerie El Bahr · C-003");
  if (billing !== "Facturable") await choose(page, page, "Facturation", billing);
  const line = page.getByRole("row", { name: "Ligne 1", exact: true });
  await choose(page, line, "Produit", "Sardine · SA-010");
  await line.getByLabel("Poids (kg)").fill("2");
  await page.getByRole("button", { name: "Enregistrer le brouillon" }).click();
  await expect(page.getByText(/Brouillon VE-[\d-]+ enregistré/)).toBeVisible();
  await page.getByRole("button", { name: "Valider le bon de livraison" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^BL-\d{4}-\d+$/);
}

test("D-285: a contested receipt is greyed out on a new supplier invoice until the dispute is lifted", async ({
  page,
}) => {
  test.slow();
  const number = await newReceipt(page);

  await page.getByRole("button", { name: "Contester" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Contester" }).click();
  await expect(dialog.getByText("Indiquez le motif de la contestation.")).toBeVisible();
  await dialog.getByLabel("Motif de contestation").fill("Deux caisses abîmées");
  await dialog.getByRole("button", { name: "Contester" }).click();
  await expect(page.getByText(`Réception ${number} contestée.`)).toBeVisible();
  await expect(page.getByRole("note").filter({ hasText: "Réception contestée" })).toContainText("Deux caisses abîmées");

  // The supplier invoice form shows it, greyed out.
  await page.goto("/achats/factures/nouvelle");
  await choose(page, page, "Fournisseur", "Aqua Monastir");
  const row = page.getByRole("row", { name: new RegExp(number) });
  await expect(row).toContainText("Contestée");
  await expect(row.getByRole("checkbox")).toBeDisabled();

  // Lifted: it can be invoiced again.
  await page.goBack();
  await page.goto("/achats");
  await page.getByLabel("Contestées seulement").check();
  await page.getByRole("link", { name: number }).click();
  await page.getByRole("button", { name: "Lever la contestation" }).click();
  await page.getByRole("dialog").getByLabel("Règlement de la contestation").fill("Avoir fournisseur accepté");
  await page.getByRole("dialog").getByRole("button", { name: "Lever la contestation" }).click();
  await expect(page.getByRole("note").filter({ hasText: "Contestation levée" })).toContainText(
    "Avoir fournisseur accepté",
  );
});

test("D-288: a PDF is attached to a receipt, listed, then removed", async ({ page }) => {
  test.slow();
  await newReceipt(page);
  await expect(page.getByText("Documents associés")).toBeVisible();
  await page.getByPlaceholder("Note (facultatif)").fill("BL du fournisseur");
  await page
    .getByText("Joindre un fichier")
    .setInputFiles({ name: "bl-aqua.pdf", mimeType: "application/pdf", buffer: PDF });
  await expect(page.getByText("bl-aqua.pdf joint.")).toBeVisible();
  const link = page.getByRole("link", { name: "bl-aqua.pdf" });
  await expect(link).toBeVisible();
  await expect(page.getByText(/BL du fournisseur/)).toBeVisible();

  await page.getByRole("button", { name: "Retirer bl-aqua.pdf" }).click();
  await expect(page.getByText("Document retiré.")).toBeVisible();
  await expect(link).toHaveCount(0);
});

test("D-286: an offered BL owes nothing; a non-invoiced one cannot be invoiced and switches back", async ({ page }) => {
  test.slow();
  await newBl(page, "Offert");
  await expect(page.getByText("Offert", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("region", { name: /^Bon de livraison BL-/ })).toContainText(/Reste dû\s*0,000\sDT/);
  await expect(page.getByRole("button", { name: "Facturer" })).toHaveCount(0);

  await newBl(page, "Non facturable");
  await expect(page.getByText("Non facturable", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Facturer" })).toHaveCount(0);
  await page.getByRole("button", { name: "Rendre facturable" }).click();
  await expect(page.getByText(/ : Facturable\./)).toBeVisible();
  await expect(page.getByRole("button", { name: "Facturer" })).toBeVisible();
});

test("D-287: a fully credited invoice is billed again as a draft pointing to its credit note", async ({ page }) => {
  test.slow();
  await newBl(page, "Facturable");
  await page.getByRole("button", { name: "Facturer" }).click();
  await expect(page.getByRole("heading", { name: /^B(ROUILLON|FA)-/, level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Émettre la facture" }).click();
  await page.getByRole("button", { name: "Émettre", exact: true }).click();
  await expect(page.getByRole("heading", { name: /^FA-\d{4}-\d{4}$/, level: 1 })).toBeVisible();
  const original = (await page.getByRole("heading", { level: 1 }).textContent()) ?? "";

  await page.getByRole("button", { name: "Faire un avoir" }).click();
  await page.getByRole("radio", { name: "Non repris" }).check();
  await page.getByLabel("Motif").fill("Mauvais client sur la facture");
  await page.getByRole("button", { name: "Créer l'avoir" }).click();
  await expect(page.getByText(/Avoir AV-\d{4}-\d{4} créé/)).toBeVisible();

  await page.getByRole("button", { name: "Refacturer" }).click();
  await expect(page.getByText("Brouillon de refacturation prêt")).toBeVisible();
  await expect(page.getByRole("heading", { name: /^B(ROUILLON|FA)-/, level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: original })).toBeVisible();
  await expect(page.getByText(/avoir AV-\d{4}-\d{4}/)).toBeVisible();
});

test("D-289: two suppliers are asked, their offers compared, one order made per chosen supplier", async ({ page }) => {
  test.slow();
  await page.goto("/achats/demandes");
  await expect(page.getByRole("heading", { name: "Demandes de prix", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Nouvelle demande de prix" }).click();
  await page.getByRole("checkbox", { name: "Aqua Monastir" }).check();
  await page.getByRole("checkbox", { name: "Mareyeur Port de Sfax" }).check();
  const first = page.getByRole("group", { name: "Produit 1" });
  await choose(page, first, "Produit", "Loup de mer · LO-004");
  await first.getByLabel("Poids (kg)").fill("40");
  await page.getByRole("button", { name: "Ajouter un produit" }).click();
  const second = page.getByRole("group", { name: "Produit 2" });
  await choose(page, second, "Produit", "Dorade royale · DO-003");
  await second.getByLabel("Poids (kg)").fill("25");
  await page.getByRole("button", { name: "Enregistrer la demande" }).click();
  await expect(page.getByRole("heading", { name: /^DD-\d{4}-\d{4}$/, level: 1 })).toBeVisible();

  // The offers are typed as they come: Aqua Monastir is cheaper on loup, the port on dorade.
  const loup = page.getByLabel("Loup de mer", { exact: true });
  const dorade = page.getByLabel("Dorade royale", { exact: true });
  await loup.nth(0).fill("21,500");
  await dorade.nth(0).fill("26,000");
  await page.getByLabel("Référence de l'offre").nth(0).fill("AQM-77");
  await page.getByRole("button", { name: "Enregistrer l'offre" }).nth(0).click();
  await expect(page.getByText("Offre de Aqua Monastir enregistrée.")).toBeVisible();
  await loup.nth(1).fill("23,000");
  await dorade.nth(1).fill("24,500");
  await page.getByRole("button", { name: "Enregistrer l'offre" }).nth(1).click();
  await expect(page.getByText("Offre de Mareyeur Port de Sfax enregistrée.")).toBeVisible();

  // The cheapest offer is proposed for each product.
  await expect(page.getByRole("radio", { name: "Choisir Aqua Monastir pour Loup de mer" })).toBeChecked();
  await expect(page.getByRole("radio", { name: "Choisir Mareyeur Port de Sfax pour Dorade royale" })).toBeChecked();
  await page.getByRole("button", { name: "Passer les commandes (2 fournisseurs)" }).click();
  await expect(page.getByText("Commandes d'achat créées.")).toBeVisible();
  await expect(page.getByText("Commandée", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /^Commande BA-\d+$/ })).toHaveCount(2);
});
