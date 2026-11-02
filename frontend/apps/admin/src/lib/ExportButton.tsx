import { useTranslation } from "@frutti/i18n";
import { Button } from "@frutti/ui";

/** Downloads the list as an Excel file with the filters and the sort in force, every row (not only this page). */
export function ExportButton({ href }: { href: string }) {
  const { t } = useTranslation();
  return (
    <Button asChild>
      <a href={href} download>
        {t("common.table.export")}
      </a>
    </Button>
  );
}
