import { useTranslation } from "@frutti/i18n";
import { cn } from "@frutti/ui";
import { NavLink } from "react-router";

/** Purchase orders, purchases at the port, receipts, invoices and payments: the lists of the "Achats" module. */
export function PurchasingTabs() {
  const { t } = useTranslation();
  const tabs = [
    { to: "/achats/bons", label: t("admin.purchasing.orders"), end: false },
    { to: "/achats/terrain", label: t("admin.purchasing.fieldPurchases"), end: false },
    { to: "/achats", label: t("admin.purchasing.receipts"), end: true },
    { to: "/achats/factures", label: t("admin.purchasing.invoices"), end: false },
    { to: "/achats/paiements", label: t("admin.purchasing.payments"), end: false },
    { to: "/achats/dettes", label: t("admin.purchasing.debts"), end: false },
    { to: "/achats/reglements", label: t("admin.purchasing.settlements"), end: false },
  ];
  return (
    <nav aria-label={t("admin.purchasing.tabs")} className="flex w-fit rounded-control bg-surface-2 p-1">
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) =>
            cn(
              "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
              isActive && "bg-surface text-ink shadow-card",
            )
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
