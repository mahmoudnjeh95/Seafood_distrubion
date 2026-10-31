import { useTranslation } from "@frutti/i18n";
import { cn } from "@frutti/ui";
import { NavLink } from "react-router";

// The stock module's sections, under the one "Stock" entry of the menu (the prototype's navigation).
const TABS = [
  { to: "/stock", label: "admin.stockTabs.places", end: true },
  { to: "/stock/caisses", label: "admin.stockTabs.boxes", end: false },
  { to: "/stock/pertes", label: "admin.stockTabs.losses", end: false },
  { to: "/stock/mouvements", label: "admin.stockTabs.movements", end: false },
  { to: "/stock/inventaires", label: "admin.stockTabs.counts", end: false },
] as const;

/** Links between the sections of the stock module, the current one marked. */
export function StockTabs() {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("admin.stockTabs.label")} className="flex flex-wrap gap-1 border-b border-line">
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) =>
            cn(
              "-mb-px border-b-2 border-transparent px-3 py-2 text-[0.9rem] font-semibold text-ink-2 hover:text-ink",
              isActive && "border-coral text-ink",
            )
          }
        >
          {t(tab.label)}
        </NavLink>
      ))}
    </nav>
  );
}
