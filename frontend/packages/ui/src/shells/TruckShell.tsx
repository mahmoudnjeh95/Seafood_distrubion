import { useTranslation } from "@frutti/i18n";
import { type ReactNode, useState } from "react";
import { NavLink } from "react-router";

import type { IconName } from "../icon-names";
import { Icon } from "../icons";
import { LogoutDialog } from "./LogoutDialog";

export interface TruckTab {
  to: string;
  label: string;
  icon: IconName;
}

interface Props {
  tabs: TruckTab[];
  /** Small line above the title: the truck, once trucks exist. */
  eyebrow: string;
  title: string;
  /** Short facts under the title (route, temperature...). */
  chips?: { icon: IconName; label: string }[];
  /** The company logo from Paramètres, shown on a white tile at the start of the header. */
  logoUrl?: string | null;
  /** Shown at the start of the header instead of the logo, e.g. the way back to Ma journée (D-171). */
  leading?: ReactNode;
  /** Shown before the logout button, e.g. the notification bell (D-175). */
  actions?: ReactNode;
  onLogout: () => void;
  /** Said in the logout window instead of the plain question, e.g. actions not sent yet. */
  logoutWarning?: ReactNode;
  children: ReactNode;
}

/** Driver frame: one phone-width column with a blue header, a scrolling body and a bottom tab bar. */
export function TruckShell({
  tabs,
  eyebrow,
  title,
  chips = [],
  logoUrl,
  leading,
  actions,
  onLogout,
  logoutWarning,
  children,
}: Props) {
  const [leaving, setLeaving] = useState(false);
  const { t } = useTranslation();
  return (
    <div className="mx-auto flex h-dvh w-full max-w-[480px] flex-col bg-bg min-[481px]:border-x min-[481px]:border-line">
      <header className="bg-linear-150 from-[#0c3b4e] to-[#0f5e7a] px-[18px] pt-[max(14px,env(safe-area-inset-top))] pb-3 text-white">
        <div className="flex items-center gap-3">
          {leading ??
            (logoUrl && (
              <img
                src={logoUrl}
                alt=""
                className="h-10 w-auto max-w-[96px] flex-none rounded-[10px] bg-white object-contain p-1"
              />
            ))}
          <div className="min-w-0 flex-1">
            <span className="eyebrow text-[#9fd0e0]">{eyebrow}</span>
            <h2 className="truncate text-[1.1rem] text-white">{title}</h2>
          </div>
          {actions}
          <button
            type="button"
            onClick={() => setLeaving(true)}
            aria-label={t("common.logout")}
            title={t("common.logout")}
            className="grid size-9 flex-none place-items-center rounded-full bg-white/15"
          >
            <Icon name="return" className="size-[18px]" />
          </button>
        </div>
        {chips.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {chips.map((chip) => (
              <span
                key={chip.label}
                className="flex items-center gap-[5px] rounded-full bg-white/15 px-2.5 py-1 text-[0.78rem]"
              >
                <Icon name={chip.icon} className="size-3.5" />
                {chip.label}
              </span>
            ))}
          </div>
        )}
      </header>

      <main className="flex flex-1 flex-col gap-3 overflow-y-auto p-3.5">{children}</main>

      <nav
        aria-label={t("truck.navigation")}
        className="grid border-t border-line bg-surface px-1 pt-1.5 pb-[max(10px,env(safe-area-inset-bottom))]"
        style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}
      >
        {tabs.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.to === "/"}
            className="flex flex-col items-center gap-0.5 py-1.5 text-[0.7rem] font-semibold text-ink-2 aria-[current=page]:text-coral"
          >
            <Icon name={tab.icon} />
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <LogoutDialog open={leaving} onOpenChange={setLeaving} onLogout={onLogout} warning={logoutWarning} />
    </div>
  );
}
