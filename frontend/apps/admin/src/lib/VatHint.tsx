import { type Product, useListVatProducts } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";

import type { Line } from "./lines";

/**
 * "Acheté avec TVA" (D-202): the products of these rows that have kilos in stock bought with VAT. A quote or a sale
 * of them carries VAT, and their invoice cannot be issued without it (the server refuses).
 */
export function VatHint({ lines, products }: { lines: readonly Line[]; products: readonly Product[] }) {
  const { t } = useTranslation();
  const vat = useListVatProducts();
  const ids = new Set((vat.data?.products ?? []).map(String));
  const names = [...new Set(lines.filter((line) => ids.has(line.product)).map((line) => line.product))].map(
    (id) => products.find((product) => String(product.id) === id)?.name ?? id,
  );
  if (names.length === 0) return null;
  return (
    <p role="status" className="rounded-chip bg-warn-soft px-3 py-2 text-[0.88rem] font-semibold text-warn">
      {t("admin.lines.vatHint", { products: names.join(", ") })}
    </p>
  );
}
