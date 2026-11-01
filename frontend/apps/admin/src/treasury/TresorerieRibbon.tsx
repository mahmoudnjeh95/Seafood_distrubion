// The ribbon of the treasury module (P9-T08): the screens of the treasury as a toolbar of large icon buttons, the way
// the office is used to it. Each treasury screen shows it at the top; the current one is highlighted.
import { useTranslation } from "@frutti/i18n";
import { cn, Icon, type IconName } from "@frutti/ui";
import { Link } from "react-router";

export type RibbonScreen =
  "encaissement" | "decaissement" | "banque" | "portefeuille" | "bordereau" | "ordre" | "factureVente" | "factureAchat";

type RibbonGroup = { id: "treasury" | "invoices"; screens: { id: RibbonScreen; to: string; icon: IconName }[] };

// Agence bancaire, caisse liquide and the journals wait for the treasury accounts (P9-T05): not on the ribbon yet.
const GROUPS: RibbonGroup[] = [
  {
    id: "treasury",
    screens: [
      { id: "encaissement", to: "/reglements", icon: "cash" },
      { id: "decaissement", to: "/achats/paiements", icon: "wallet" },
      { id: "banque", to: "/tresorerie/banques", icon: "badge" },
      { id: "portefeuille", to: "/tresorerie/portefeuille", icon: "receipt" },
      { id: "bordereau", to: "/tresorerie/bordereau", icon: "calcheck" },
      { id: "ordre", to: "/achats/reglements", icon: "check" },
    ],
  },
  {
    id: "invoices",
    screens: [
      { id: "factureVente", to: "/tresorerie/etats/ventes", icon: "receipt" },
      { id: "factureAchat", to: "/tresorerie/etats/achats", icon: "cart" },
    ],
  },
];

export function TresorerieRibbon({ active }: { active: RibbonScreen }) {
  const { t } = useTranslation();
  return (
    <nav
      aria-label={t("admin.treasury.ribbon.label")}
      className="mb-4 flex flex-wrap items-stretch gap-3 rounded-card border border-line bg-surface p-2 shadow-card"
    >
      {GROUPS.map((group, index) => (
        <div
          key={group.id}
          className={cn("flex flex-col justify-between gap-1", index > 0 && "border-s border-line ps-3")}
        >
          <div className="flex flex-wrap gap-1">
            {group.screens.map((screen) => {
              const current = screen.id === active;
              return (
                <Link
                  key={screen.id}
                  to={screen.to}
                  aria-current={current ? "page" : undefined}
                  className={cn(
                    "flex min-w-[92px] flex-col items-center gap-1 rounded-control border px-3 py-2 text-center text-[0.8rem] font-semibold",
                    current
                      ? "border-sea bg-sea-soft text-sea"
                      : "border-transparent text-ink-2 hover:bg-surface-2 hover:text-ink",
                  )}
                >
                  <Icon name={screen.icon} className="h-6 w-6" aria-hidden />
                  <span>{t(`admin.treasury.ribbon.screens.${screen.id}`)}</span>
                </Link>
              );
            })}
          </div>
          <span className="text-center text-[0.72rem] uppercase tracking-wide text-ink-2">
            {t(`admin.treasury.ribbon.groups.${group.id}`)}
          </span>
        </div>
      ))}
    </nav>
  );
}
