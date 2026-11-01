import { expect, type Page, test } from "@playwright/test";

import { OWNER_STATE } from "./owner";

// Demo employees and payroll created by `manage.py seed_dev` (stand-ins of docs/spec/sample/employees.csv).
test.use({ storageState: OWNER_STATE });

async function openEmployees(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Personnel & salaires" }).click();
  await expect(page.getByRole("heading", { name: "Paie du mois", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: "Employés" }).click();
  await expect(page.getByRole("heading", { name: "Employés", level: 1 })).toBeVisible();
}

async function createEmployee(page: Page, name: string, salary: string) {
  await page.getByRole("button", { name: "Nouvel employé" }).click();
  const dialog = page.getByRole("dialog", { name: "Nouvel employé" });
  await dialog.getByLabel("Nom", { exact: true }).fill(name);
  await dialog.getByLabel("Poste").fill("Manutentionnaire");
  await dialog.getByLabel("Salaire mensuel brut (DT)").fill(salary);
  await dialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByText("Employé créé.")).toBeVisible();
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();
}

test("the owner sees the demo employees, creates one and records a day on a lot at salary / 26", async ({ page }) => {
  // The development database is kept between runs: a new name every time.
  const name = `Employé E2E ${Date.now()}`;
  await openEmployees(page);

  const demo = page.getByRole("row").filter({ hasText: "Hedi Z." });
  await expect(demo).toContainText("E-006");
  await expect(demo).toContainText(/1\s100,000\sDT/);

  await createEmployee(page, name, "1 000");
  await expect(page.getByText(/^E-\d{3}$/)).toBeVisible();
  await expect(page.getByText("17,07 %")).toBeVisible();
  await expect(page.getByText("9,18 %")).toBeVisible();

  await expect(page.getByRole("heading", { name: "Jours sur lot" })).toBeVisible();
  await page.getByLabel("Lot", { exact: true }).click();
  await page.getByRole("option").nth(1).click();
  await page.getByRole("button", { name: "Ajouter" }).click();

  // One whole day: 1 000 / 26 = 38,462 DT, rounded once.
  await expect(page.getByText("Jour enregistré.")).toBeVisible();
  const row = page.getByRole("row").filter({ hasText: /L-\d{4}/ });
  await expect(row).toContainText(/38,462\sDT/);
  await expect(row).toContainText("1,00");
});

test("the owner generates the month, adjusts the approved salary and pays it", async ({ page }) => {
  const name = `Paie E2E ${Date.now()}`;
  await openEmployees(page);
  await createEmployee(page, name, "1 300");

  await page.getByRole("link", { name: "Personnel & salaires" }).click();
  await expect(page.getByRole("heading", { name: "Paie du mois", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Générer le mois" }).click();

  // The new employee gets an approved salary at their fixed salary (D-228); the demo ones already have theirs.
  const row = page.getByRole("row").filter({ hasText: name });
  await expect(row).toContainText("Approuvée");
  await expect(row).toContainText(/1\s300,000\sDT/);
  // An approved salary has no edit button: corrections are adjustments.
  await expect(row.getByRole("button", { name: "Modifier" })).toHaveCount(0);

  // 1 300 gross, the employee's own CNSS 9,18 % = 119,340 withheld: net 1 180,660.
  await expect(row).toContainText(/1\s180,660\sDT/);
  await row.getByRole("button", { name: "Ajuster" }).click();
  const adjust = page.getByRole("dialog", { name: `Ajuster la paie de ${name}` });
  await adjust.getByLabel("Montant (DT, négatif pour réduire)").fill("100");
  await adjust.getByLabel("Motif").fill("Prime de fin d'année");
  await adjust.getByRole("button", { name: "Enregistrer l'ajustement" }).click();
  await expect(page.getByText("Ajustement enregistré.")).toBeVisible();
  await expect(row).toContainText(/1\s280,660\sDT/);

  await row.getByRole("button", { name: "Payer" }).click();
  const pay = page.getByRole("dialog", { name: `Payer ${name}` });
  // The amount field shows its thousands separator (D-221).
  await expect(pay.getByLabel("Montant (DT)")).toHaveValue(/^1\s280,660$/);
  await pay.getByRole("button", { name: "Enregistrer le paiement" }).click();
  await expect(page.getByText(/Paiement PS-\d{4}-\d{4} enregistré\./)).toBeVisible();
  await expect(row).toContainText("Soldé");
});
