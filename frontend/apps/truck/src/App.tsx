import {
  createQueryClient,
  LanguageSwitch,
  LoginPage,
  NotificationCenter,
  RequireRole,
  type Session,
  useLogout,
  useSession,
} from "@frutti/auth";
import { useGetMyDay } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Sprite, Toaster, TruckShell, type TruckTab, useFavicon } from "@frutti/ui";
import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router";

import { BackToDay } from "./BackToDay";
import { ClosingPage } from "./ClosingPage";
import { DayPage } from "./DayPage";
import { DeliveriesPage } from "./DeliveriesPage";
import { ExpensePage } from "./ExpensePage";
import { HistoryDayPage, HistoryPage } from "./HistoryPage";
import { LossPage } from "./LossPage";
import { MyPurchasesPage } from "./MyPurchasesPage";
import { forgetSavedData } from "./offline";
import { useTruckStock } from "./myStock";
import { OfflineBanner } from "./OfflineBanner";
import { PaymentPage } from "./PaymentPage";
import { PickupPage } from "./PickupPage";
import { PriceNotice } from "./PriceNotice";
import { PurchaseNotice } from "./PurchaseNotice";
import { PurchasePage } from "./PurchasePage";
import { usePriceWatch } from "./priceWatch";
import { useQueue } from "./queue";
import { SalePage } from "./SalePage";
import { ScreenError } from "./ScreenError";
import { StockPage } from "./StockPage";
import { SyncStatus } from "./SyncStatus";
import { forgetPoints, TRACKING_ENABLED, useLocationTracking } from "./tracking";

const queryClient = createQueryClient();
// Without signal, ask anyway: the phone answers from what it saved (public/sw.js) instead of waiting forever.
queryClient.setDefaultOptions({ queries: { networkMode: "offlineFirst" } });

// The phone keeps a copy of the company logo, so the login screen and the browser-tab icon show it before any login
// (D-125, D-154). It is a data: address, not the logo's URL: the server serves the logo only to a logged-in user, so
// the URL fails on the login screen. Not a secret: it is the logo every document already carries. Storage can be
// blocked: then the default icon stays.
const LOGO_KEY = "frutti-truck-logo";

function rememberedLogo(): string | null {
  try {
    return localStorage.getItem(LOGO_KEY);
  } catch {
    return null;
  }
}

function remember(logo: string | null): void {
  try {
    if (logo) localStorage.setItem(LOGO_KEY, logo);
    else localStorage.removeItem(LOGO_KEY);
  } catch {
    // Not saved: the next login screen shows the default icon until a login works again.
  }
}

/** The logo as a data: address, read with the logged-in driver's session. */
async function logoAsDataUrl(url: string): Promise<string | null> {
  const response = await fetch(url);
  if (!response.ok) return null;
  const blob = await response.blob();
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : null);
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(blob);
  });
}

/** The company logo for the login screen and the tab icon: copied from the server while logged in, else the copy
 * kept on this phone. A company without a logo clears the copy. */
function useCompanyLogo(): string | null {
  const session = useSession();
  const loggedIn = Boolean(session.data);
  const serverLogo = session.data?.organization.logo_url ?? null;
  const [logo, setLogo] = useState<string | null>(rememberedLogo);
  useEffect(() => {
    if (!loggedIn) return;
    if (!serverLogo) {
      remember(null);
      return;
    }
    let cancelled = false;
    logoAsDataUrl(serverLogo)
      .then((copy) => {
        if (!copy) return;
        remember(copy);
        if (!cancelled) setLogo(copy);
      })
      .catch(() => {
        // Offline or refused: the copy kept on this phone stays.
      });
    return () => {
      cancelled = true;
    };
  }, [loggedIn, serverLogo]);
  // A logged-in company without a logo shows none, even when an older copy is still on the phone.
  return loggedIn && !serverLogo ? null : logo;
}

// Same four tabs as the approved prototype.
function useTabs(): TruckTab[] {
  const { t } = useTranslation();
  return [
    { to: "/", label: t("truck.tabs.day"), icon: "home" },
    { to: "/stock", label: t("truck.tabs.stock"), icon: "box" },
    { to: "/vente", label: t("truck.tabs.sale"), icon: "receipt" },
    { to: "/cloture", label: t("truck.tabs.closing"), icon: "lock" },
  ];
}

function Shell({ session }: { session: Session }) {
  const { t } = useTranslation();
  const tabs = useTabs();
  const logout = useLogout();
  const location = useLocation();
  // Logging out erases what the phone still has to send, so the logout window says how much (D-194).
  const waiting = useQueue().filter((item) => item.status === "pending").length;
  // The prices are watched on every screen, so a change is announced wherever the driver is (P3-T02).
  const stock = useTruckStock(session.truck !== null);
  usePriceWatch(stock.data);
  // The phone follows the day's position while the day runs (D-164); switched off for now (D-180).
  const day = useGetMyDay({ query: { retry: false, enabled: session.truck !== null } });
  const tracking = useLocationTracking(TRACKING_ENABLED && day.data !== undefined && day.data.ended_at === null);
  return (
    <TruckShell
      tabs={tabs}
      logoUrl={session.organization.logo_url}
      leading={location.pathname === "/" ? undefined : <BackToDay />}
      eyebrow={session.truck?.name ?? session.organization.name}
      title={t("truck.hello", { name: session.user.first_name || session.user.username })}
      actions={<NotificationCenter userId={session.user.id} tone="dark" />}
      logoutWarning={waiting > 0 ? t("truck.sync.logoutWarning", { count: waiting }) : undefined}
      onLogout={() => {
        void forgetSavedData();
        forgetPoints();
        logout.mutate();
      }}
    >
      <OfflineBanner />
      {(tracking === "denied" || tracking === "unavailable") && (
        <p role="status" className="rounded-control bg-warn-soft px-3 py-2 text-warn">
          {t(`truck.tracking.${tracking}`)}
        </p>
      )}
      <PriceNotice />
      {/* The office's decisions on the driver's purchases at the port, for a driver who buys (D-158). */}
      <PurchaseNotice enabled={session.can_buy} />
      <SyncStatus />
      <ScreenError resetKey={location.pathname}>
        <Outlet />
      </ScreenError>
      <LanguageSwitch className="mt-2 self-center" />
    </TruckShell>
  );
}

function AppRoutes() {
  const { t } = useTranslation();
  const logo = useCompanyLogo();
  useFavicon(logo);
  return (
    <Routes>
      <Route path="/login" element={<LoginPage title={t("truck.appName")} withLanguage logoUrl={logo} />} />
      <Route
        element={
          <RequireRole allow={["driver"]} wrongAppMessage={t("truck.wrongApp")}>
            {(session) => <Shell session={session} />}
          </RequireRole>
        }
      >
        <Route path="/" element={<DayPage />} />
        <Route path="/stock" element={<StockPage />} />
        <Route path="/livraisons" element={<DeliveriesPage />} />
        <Route path="/vente" element={<SalePage />} />
        <Route path="/cloture" element={<ClosingPage />} />
        <Route path="/historique" element={<HistoryPage />} />
        <Route path="/historique/:dayId" element={<HistoryDayPage />} />
        <Route path="/depense" element={<ExpensePage />} />
        <Route path="/encaissement" element={<PaymentPage />} />
        <Route path="/perte" element={<LossPage />} />
        <Route path="/reprise" element={<PickupPage />} />
        <Route path="/achat" element={<PurchasePage />} />
        <Route path="/achats" element={<MyPurchasesPage />} />
        <Route path="/achats/:purchaseId" element={<PurchasePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Sprite />
      <Toaster />
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
