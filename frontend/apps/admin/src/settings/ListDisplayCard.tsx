import { useTranslation } from "@frutti/i18n";
import { Card, CardTitle, PAGE_SIZES, rememberedPageSize, rememberPageSize, setShowTotals, useShowTotals } from "@frutti/ui";
import { useState } from "react";

/** How lists look for this person on this device: the "Total de la page" row and the number of rows per page. */
export function ListDisplayCard() {
  const { t } = useTranslation();
  const showTotals = useShowTotals();
  const [pageSize, setPageSize] = useState(() => rememberedPageSize(50));
  return (
    <Card>
      <CardTitle>{t("admin.settings.display")}</CardTitle>
      <p className="mb-4 text-[0.85rem] text-ink-2">{t("admin.settings.displayHint")}</p>
      <label className="mb-3 flex items-center gap-2 text-[0.9rem]">
        <input type="checkbox" checked={showTotals} onChange={(event) => setShowTotals(event.target.checked)} />
        {t("admin.settings.showTotals")}
      </label>
      <label className="flex items-center gap-2 text-[0.9rem]">
        {t("admin.settings.defaultPageSize")}
        <select
          className="rounded-md border border-line bg-surface px-1.5 py-1"
          value={pageSize}
          onChange={(event) => {
            const size = Number(event.target.value);
            setPageSize(size);
            rememberPageSize(size);
          }}
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>
    </Card>
  );
}
