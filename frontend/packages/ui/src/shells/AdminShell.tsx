import { useTranslation } from "@frutti/i18n";
import { type ReactNode, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";

import { Button } from "../components/button";
import { Pill } from "../components/pill";
import type { IconName } from "../icon-names";
import { Icon } from "../icons";
import { Brand } from "./Brand";
import { LogoutDialog } from "./LogoutDialog";
import { ThemeToggle } from "./ThemeToggle";

export interface AdminNavGroup {
  label: string;
  items: { to: string; label: string; icon: IconName; badge?: string }[];
}

interface Props {
  nav: AdminNavGroup[];
  user: { name: string; role: string; avatarUrl?: string | null };
  /** The company logo from Paramètres; the default mark without one. */
  logoUrl?: string | null;
  /** Shown in the top bar before the theme switch, e.g. the notification bell (D-175). */
  actions?: ReactNode;
  onLogout: () => void;
  children: ReactNode;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}

/** "Retour" above every page that is not a menu entry: the previous page, or the menu entry it belongs to. */
function BackLink({ nav }: { nav: AdminNavGroup[] }) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const entries = nav.flatMap((group) => group.items.map((item) => item.to));
  if (entries.includes(pathname.replace(/\/+$/, "") || "/")) return null;
  const parent = entries
    .filter((to) => to !== "/" && pathname.startsWith(`${to}/`))
    .sort((a, b) => b.length - a.length)[0];
  const goBack = () => {
    const index = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (index > 0) void navigate(-1);
    else void navigate(parent ?? "/");
  };
  return (
    <Button variant="ghost" onClick={goBack} className="self-start print:hidden">
      <span aria-hidden className="rtl:-scale-x-100">
        ←
      </span>
      {t("common.back")}
    </Button>
  );
}

/**
 * Back-office frame: sticky top bar, module sidebar, page area. On wide screens the sidebar is pinned under the bar and
 * scrolls on its own; its scrolling never moves the page. On small screens it is a scrolling strip.
 */
export function AdminShell({ nav, user, logoUrl, actions, onLogout, children }: Props) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const [leaving, setLeaving] = useState(false);
  // The menu entry that owns this page: the longest entry the path is under, so "Règlements fournisseurs"
  // (/achats/reglements) lights up alone and not "Achats" (/achats) too.
  const path = pathname.replace(/\/+$/, "") || "/";
  const activeTo = nav
    .flatMap((group) => group.items.map((item) => item.to))
    .filter((to) => (to === "/" ? path === "/" : path === to || path.startsWith(`${to}/`)))
    .sort((a, b) => b.length - a.length)[0];
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 print:hidden flex flex-wrap items-center gap-4 border-b border-line bg-surface/90 px-5 py-3 backdrop-blur-md max-sm:gap-2.5 max-sm:px-4 max-sm:py-2.5">
        <Brand logoUrl={logoUrl} />
        <div className="flex-1" />
        {actions}
        <ThemeToggle />
        <div className="flex items-center gap-2.5">
          <NavLink
            to="/profil"
            aria-label={t("admin.profile.open")}
            title={t("admin.profile.open")}
            className="flex items-center gap-2.5 rounded-[10px] hover:opacity-80"
          >
            {user.avatarUrl ? (
              <img src={user.avatarUrl} alt="" className="size-[30px] flex-none rounded-full object-cover" />
            ) : (
              <div className="grid size-[30px] flex-none place-items-center rounded-full bg-sea-soft text-[0.75rem] font-bold text-sea">
                {initials(user.name)}
              </div>
            )}
            <div className="leading-tight max-sm:hidden">
              <div className="font-semibold">{user.name}</div>
              <Pill tone="sea" className="px-[7px] py-px text-[0.68rem]">
                {user.role}
              </Pill>
            </div>
          </NavLink>

          <Button
            variant="ghost"
            size="icon"
            aria-label={t("common.logout")}
            title={t("common.logout")}
            onClick={() => setLeaving(true)}
          >
            <Icon name="return" />
          </Button>
        </div>
      </header>

      <div className="grid min-h-[calc(100dvh-62px)] grid-cols-[232px_minmax(0,1fr)] max-[860px]:grid-cols-1 print:block">
        <nav
          aria-label={t("admin.modules")}
          className="flex flex-col gap-0.5 border-e border-line bg-surface px-3 py-[18px] print:hidden min-[861px]:sticky min-[861px]:top-[62px] min-[861px]:h-[calc(100dvh-62px)] min-[861px]:self-start min-[861px]:overflow-y-auto min-[861px]:overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden max-[860px]:flex-row max-[860px]:gap-1.5 max-[860px]:overflow-x-auto max-[860px]:border-e-0 max-[860px]:border-b max-[860px]:px-4 max-[860px]:py-2.5"
        >
          {nav.map((group) => (
            <div key={group.label} className="contents">
              <div className="eyebrow mx-2.5 mt-3.5 mb-1.5 max-[860px]:hidden">{group.label}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={() =>
                    `flex flex-none items-center gap-[11px] rounded-[10px] px-3 py-[9px] whitespace-nowrap ${
                      activeTo === item.to
                        ? "bg-sea-soft font-bold text-sea"
                        : "font-medium text-ink-2 hover:bg-surface-2 hover:text-ink"
                    }`
                  }
                >
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                  {item.badge && (
                    <span className="ms-auto rounded-full bg-coral px-[7px] py-px text-[0.68rem] font-bold text-white">
                      {item.badge}
                    </span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <main className="flex min-w-0 flex-col gap-[22px] px-8 pt-7 pb-12 print:p-0 max-[860px]:px-4 max-[860px]:pt-5 max-[860px]:pb-10">
          <BackLink nav={nav} />
          {children}
        </main>
      </div>
      <LogoutDialog open={leaving} onOpenChange={setLeaving} onLogout={onLogout} />
    </div>
  );
}

/** Title row of a page: eyebrow, heading, and the page's actions on the right. */
export function PageHeader({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end gap-4">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
      </div>
      <div className="min-w-2 flex-1" />
      {children}
    </div>
  );
}
