import {
  createQueryClient,
  LanguageSwitch,
  LoginPage,
  TrainingTag,
  NotificationCenter,
  RequireRole,
  type Session,
  useLogout,
  useSession,
} from "@frutti/auth";
import { useGetMyDay } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Card, Sprite, Toaster, TruckShell, type TruckTab, useFavicon } from "@frutti/ui";
import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BrowserRouter, Link, Navigate, Outlet, Route, Routes, useLocation } from "react-router";

import { BackToDay } from "./BackToDay";
import { ClosingPage } from "./ClosingPage";
import { remember, rememberedLogo } from "./companyLogo";
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

// Same four tabs as the approved prototype. `locked`: only "Ma journée" works (a new load to confirm, D-281).
function useTabs(locked: boolean): TruckTab[] {
  const { t } = useTranslation();
  return [
    { to: "/", label: t("truck.tabs.day"), icon: "home" },
    { to: "/stock", label: t("truck.tabs.stock"), icon: "box", disabled: locked },
    { to: "/vente", label: t("truck.tabs.sale"), icon: "receipt", disabled: locked },
    { to: "/cloture", label: t("truck.tabs.closing"), icon: "lock", disabled: locked },
  ];
}

/** Every screen but "Ma journée" while the driver has not confirmed the new start after a new load (D-281). */
function RestartLocked() {
  const { t } = useTranslation();
  return (
    <Card className="space-y-3 border-2 border-warn">
      <p className="text-lg font-semibold">{t("truck.day.restartTitle")}</p>
      <p>{t("truck.day.restartLocked")}</p>
      <Link to="/" className="block">
        <Button size="lg" className="w-full py-4 text-lg">
          {t("truck.tabs.day")}
        </Button>
      </Link>
    </Card>
  );
}

function Shell({ session }: { session: Session }) {
  const { t } = useTranslation();
  const logout = useLogout();
  const location = useLocation();
  // Logging out erases what the phone still has to send, so the logout window says how much (D-194).
  const waiting = useQueue().filter((item) => item.status === "pending").length;
  // The prices are watched on every screen, so a change is announced wherever the driver is (P3-T02).
  const stock = useTruckStock(session.truck !== null);
  usePriceWatch(stock.data);
  // The phone follows the day's position while the day runs (D-164); switched off for now (D-180).
  // Read again every minute, so a new load that waits for the driver's confirmation shows soon (D-281).
  const day = useGetMyDay({ query: { retry: false, enabled: session.truck !== null, refetchInterval: 60_000 } });
  const tracking = useLocationTracking(TRACKING_ENABLED && day.data !== undefined && day.data.ended_at === null);
  // The office loaded the truck again after the day was sent: nothing but "Ma journée" until the driver confirms
  // the new start (D-281). The server refuses the rest too; this only says so before the driver tries.
  const locked = day.data?.restart_pending === true;
  const tabs = useTabs(locked);
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
        {locked && location.pathname !== "/" ? <RestartLocked /> : <Outlet />}
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
      <Route
        path="/login"
        element={<LoginPage title={t("truck.appName")} withLanguage logoUrl={logo} app="driver" />}
      />
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
      <TrainingTag />
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
