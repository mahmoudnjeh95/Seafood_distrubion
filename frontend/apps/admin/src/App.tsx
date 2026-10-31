import { createQueryClient, LoginPage, NotificationCenter, RequireRole, type Session, useLogout } from "@frutti/auth";
import { useTranslation } from "@frutti/i18n";
import {
  type AdminNavGroup,
  AdminShell,
  EmptyState,
  type IllustrationName,
  PageHeader,
  Sprite,
  Toaster,
  useFavicon,
} from "@frutti/ui";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useOutletContext } from "react-router";

import { DashboardPage } from "./dashboard/DashboardPage";
import { EmployeeDetailPage } from "./hr/EmployeeDetailPage";
import { EmployeesPage } from "./hr/EmployeesPage";
import { PayrollPage } from "./hr/PayrollPage";
import { ColdRoomCostPage } from "./expenses/ColdRoomCostPage";
import { DayLabourCalendarPage } from "./expenses/DayLabourCalendarPage";
import { DayLabourersPage } from "./expenses/DayLabourersPage";
import { ExpenseDetailPage } from "./expenses/ExpenseDetailPage";
import { ExpenseEditPage, ExpenseFormPage } from "./expenses/ExpenseFormPage";
import { ExpensesPage } from "./expenses/ExpensesPage";
import { FinanceSettingsPage } from "./invoices/FinanceSettingsPage";
import { InvoicePage } from "./invoices/InvoicePage";
import { InvoicesPage } from "./invoices/InvoicesPage";

import { GeneralCostsPage } from "./expenses/GeneralCostsPage";
import { ImportPage } from "./imports/ImportPage";
import { LocationsPage } from "./locations/LocationsPage";
import { TruckDayPage } from "./locations/TruckDayPage";
import { MonthClosingPage } from "./closing/MonthClosingPage";
import { ReportsPage } from "./reports/ReportsPage";
import { PartnershipsPage } from "./partnerships/PartnershipsPage";
import { ProfilePage } from "./settings/ProfilePage";
import { SettingsPage } from "./settings/SettingsPage";
import { UsersPage } from "./settings/UsersPage";
import { BoxesPage } from "./boxes/BoxesPage";
import { BatchStockPage } from "./stock/BatchStockPage";
import { MovementsPage } from "./stock/MovementsPage";
import { ProductStockPage } from "./stock/ProductStockPage";
import { PriceBoardPage } from "./prices/PriceBoardPage";
import { ProductsPage } from "./products/ProductsPage";
import { QuoteDetailPage } from "./quotes/QuoteDetailPage";
import { QuoteEditPage, QuoteFormPage } from "./quotes/QuoteFormPage";
import { QuotesPage } from "./quotes/QuotesPage";
import { SupplierInvoiceDetailPage } from "./purchasing/SupplierInvoiceDetailPage";
import { SupplierInvoiceFormPage } from "./purchasing/SupplierInvoiceFormPage";
import { SupplierInvoicesPage } from "./purchasing/SupplierInvoicesPage";
import { SupplierPaymentFormPage } from "./purchasing/SupplierPaymentFormPage";
import { SupplierPaymentsPage } from "./purchasing/SupplierPaymentsPage";
import { SupplierDebtsPage } from "./purchasing/SupplierDebtsPage";
import { SupplierSettlementsPage } from "./purchasing/SupplierSettlementsPage";
import { PurchaseOrderDetailPage } from "./orders/PurchaseOrderDetailPage";
import { PurchaseOrderFormPage } from "./orders/PurchaseOrderFormPage";
import { PurchaseOrdersPage } from "./orders/PurchaseOrdersPage";
import { ReceiptDetailPage } from "./receipts/ReceiptDetailPage";
import { ReceiptFormPage } from "./receipts/ReceiptFormPage";
import { ReceiptsPage } from "./receipts/ReceiptsPage";
import { FieldPurchaseNewPage, FieldPurchasePage } from "./fieldpurchases/FieldPurchasePage";
import { FieldPurchasesPage } from "./fieldpurchases/FieldPurchasesPage";
import { CounterSalePage } from "./sales/CounterSalePage";
import { SaleDetailPage } from "./sales/SaleDetailPage";
import { SaleEditPage, SaleFormPage } from "./sales/SaleFormPage";
import { SalesPage } from "./sales/SalesPage";
import { PaymentsPage } from "./payments/PaymentsPage";
import { CustomerDetailPage } from "./customers/CustomerDetailPage";
import { CustomersPage } from "./customers/CustomersPage";
import { SupplierDetailPage } from "./suppliers/SupplierDetailPage";
import { SuppliersPage } from "./suppliers/SuppliersPage";
import { CountPage } from "./counts/CountPage";
import { CountsPage } from "./counts/CountsPage";
import { DayClosingsPage } from "./dayclose/DayClosingsPage";
import { DocumentsPage } from "./doclist/DocumentsPage";
import { LossDetailPage } from "./losses/LossDetailPage";
import { LossesPage } from "./losses/LossesPage";
import { LossFormPage } from "./losses/LossFormPage";
import { TransferDetailPage } from "./transfers/TransferDetailPage";
import { TransferEditPage, TransferFormPage } from "./transfers/TransferFormPage";
import { TransfersPage } from "./transfers/TransfersPage";
import { SiteProductsPage } from "./webrequests/SiteProductsPage";
import { SiteSettingsPage } from "./webrequests/SiteSettingsPage";
import { WebRequestPage } from "./webrequests/WebRequestPage";
import { WebRequestsPage } from "./webrequests/WebRequestsPage";

const queryClient = createQueryClient();

// Same modules and order as the approved prototype, plus the catalogue. Each one becomes a real screen in its phase.
function useNav(): AdminNavGroup[] {
  const { t } = useTranslation();
  return [
    {
      label: t("admin.groups.steering"),
      items: [
        { to: "/", label: t("admin.nav.dashboard"), icon: "grid" },
        { to: "/rapports", label: t("admin.nav.reports"), icon: "grid" },
      ],
    },
    {
      label: t("admin.groups.sales"),
      items: [
        { to: "/devis", label: t("admin.nav.quotes"), icon: "quote" },
        { to: "/ventes", label: t("admin.nav.sales"), icon: "receipt" },
        { to: "/factures", label: t("admin.nav.invoices"), icon: "receipt" },
        { to: "/reglements", label: t("admin.nav.payments"), icon: "cash" },
        { to: "/clients", label: t("admin.nav.customers"), icon: "users" },
        { to: "/prix", label: t("admin.nav.prices"), icon: "badge" },
      ],
    },
    {
      label: t("admin.groups.goods"),
      items: [
        { to: "/stock", label: t("admin.nav.stock"), icon: "box" },
        { to: "/camions", label: t("admin.nav.truckDay"), icon: "truck" },
        { to: "/journees", label: t("admin.nav.dayClosings"), icon: "calcheck" },
        // Loading a truck is part of the driver's day, so its transfers sit here, not under Stock (D-196).
        { to: "/stock/transferts", label: t("admin.nav.transfers"), icon: "truck" },
        { to: "/produits", label: t("admin.nav.products"), icon: "snow" },
        { to: "/achats", label: t("admin.nav.purchases"), icon: "cart" },
        { to: "/achats/reglements", label: t("admin.nav.supplierSettlements"), icon: "cash" },
        { to: "/fournisseurs", label: t("admin.nav.suppliers"), icon: "anchor" },
      ],
    },
    {
      label: t("admin.groups.finance"),
      items: [
        { to: "/documents", label: t("admin.nav.documents"), icon: "receipt" },
        { to: "/charges", label: t("admin.nav.expenses"), icon: "wallet" },
        { to: "/salaires", label: t("admin.nav.payroll"), icon: "badge" },
        { to: "/partenariats", label: t("admin.nav.profitSharing"), icon: "percent" },
        { to: "/cloture", label: t("admin.nav.closing"), icon: "calcheck" },
      ],
    },
    {
      label: t("admin.groups.site"),
      items: [
        { to: "/demandes-site", label: t("admin.nav.webRequests"), icon: "cart" },
        { to: "/site-produits", label: t("admin.nav.siteProducts"), icon: "snow" },
        { to: "/site-parametres", label: t("admin.nav.siteSettings"), icon: "badge" },
      ],
    },
    {
      label: t("admin.groups.admin"),
      items: [
        { to: "/import", label: t("admin.nav.imports"), icon: "box" },
        { to: "/parametres", label: t("admin.nav.settings"), icon: "badge" },
      ],
    },
  ];
}

// Screens that exist; every other entry of the menu shows "coming soon".
const SCREENS: Record<string, ReactNode> = {
  "/documents": <DocumentsPage />,
  "/stock": <LocationsPage />,
  "/camions": <TruckDayPage />,
  "/journees": <DayClosingsPage />,
  "/produits": <ProductsPage />,
  "/achats": <ReceiptsPage />,
  "/fournisseurs": <SuppliersPage />,
  "/clients": <CustomersPage />,
  "/prix": <PriceBoardPage />,
  "/devis": <QuotesPage />,
  "/ventes": <SalesPage />,
  "/factures": <InvoicesPage />,
  "/reglements": <PaymentsPage />,
  "/salaires": <PayrollPage />,
  "/charges": <ExpensesPage />,
  "/partenariats": <PartnershipsPage />,
  "/import": <ImportPage />,
  "/parametres": (
    <OwnerOnly>
      <SettingsPage />
    </OwnerOnly>
  ),
  "/cloture": <MonthClosingPage />,
  "/rapports": <ReportsPage />,
  "/demandes-site": <WebRequestsPage />,
  "/site-produits": <SiteProductsPage />,
  "/site-parametres": <SiteSettingsPage />,
};

const ILLUSTRATIONS: Record<string, IllustrationName> = {};

function displayName(session: Session): string {
  return `${session.user.first_name} ${session.user.last_name}`.trim() || session.user.username;
}

function OwnerOnly({ children }: { children: ReactNode }) {
  const session = useOutletContext<Session>();
  return session.role === "owner" ? children : <Navigate to="/" replace />;
}

function Shell({ session }: { session: Session }) {
  const { t } = useTranslation();
  const logout = useLogout();
  const nav = useNav().map((group) => ({
    ...group,
    items: group.items.filter((item) => session.role === "owner" || item.to !== "/parametres"),
  }));
  useFavicon(session.organization.logo_url);
  return (
    <AdminShell
      nav={nav}
      user={{ name: displayName(session), role: t(`roles.${session.role}`), avatarUrl: session.user.avatar_url }}
      logoUrl={session.organization.logo_url}
      actions={<NotificationCenter userId={session.user.id} />}
      onLogout={() => logout.mutate()}
    >
      <Outlet context={session} />
    </AdminShell>
  );
}

function ComingSoon({ path, title, group }: { path: string; title: string; group: string }) {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader eyebrow={group} title={title} />
      <EmptyState illustration={ILLUSTRATIONS[path] ?? "mix"} title={t("common.comingSoon")}>
        {t("common.comingSoonBody")}
      </EmptyState>
    </>
  );
}

function AppRoutes() {
  const { t } = useTranslation();
  const nav = useNav();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage title={t("admin.appName")} />} />
      <Route
        element={
          <RequireRole allow={["owner", "manager", "accountant"]} wrongAppMessage={t("admin.wrongApp")}>
            {(session) => <Shell session={session} />}
          </RequireRole>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/profil" element={<ProfilePage />} />
        <Route
          path="/parametres/utilisateurs"
          element={
            <OwnerOnly>
              <UsersPage />
            </OwnerOnly>
          }
        />
        <Route path="/fournisseurs/:supplierId" element={<SupplierDetailPage />} />
        <Route path="/clients/:customerId" element={<CustomerDetailPage />} />
        {/* Employees and payroll (P5-T04) */}
        <Route path="/salaires/employes" element={<EmployeesPage />} />
        <Route path="/salaires/employes/:employeeId" element={<EmployeeDetailPage />} />
        {/* Quotes (P2-T03) */}
        <Route path="/devis/nouveau" element={<QuoteFormPage />} />
        <Route path="/devis/:quoteId" element={<QuoteDetailPage />} />
        <Route path="/devis/:quoteId/modifier" element={<QuoteEditPage />} />
        {/* Sales (P2-T04) */}
        <Route path="/ventes/nouvelle" element={<SaleFormPage />} />
        <Route path="/ventes/comptoir" element={<CounterSalePage />} />
        <Route path="/ventes/:saleId" element={<SaleDetailPage />} />
        <Route path="/ventes/:saleId/modifier" element={<SaleEditPage />} />
        {/* Invoices and finance settings (P2-T05) */}
        <Route path="/factures/parametres" element={<FinanceSettingsPage />} />
        <Route path="/factures/:invoiceId" element={<InvoicePage />} />
        <Route path="/achats/bons" element={<PurchaseOrdersPage />} />
        <Route path="/achats/bons/nouveau" element={<PurchaseOrderFormPage />} />
        <Route path="/achats/bons/:orderId" element={<PurchaseOrderDetailPage />} />
        {/* Buying at the port (P3-T12a, D-176) */}
        <Route path="/achats/terrain" element={<FieldPurchasesPage />} />
        <Route path="/achats/terrain/nouveau" element={<FieldPurchaseNewPage />} />
        <Route path="/achats/terrain/:purchaseId" element={<FieldPurchasePage />} />
        <Route path="/achats/nouvelle" element={<ReceiptFormPage />} />
        <Route path="/achats/:receiptId" element={<ReceiptDetailPage />} />
        <Route path="/achats/factures" element={<SupplierInvoicesPage />} />
        <Route path="/achats/factures/nouvelle" element={<SupplierInvoiceFormPage />} />
        <Route path="/achats/factures/:invoiceId" element={<SupplierInvoiceDetailPage />} />
        <Route path="/achats/factures/:invoiceId/modifier" element={<SupplierInvoiceFormPage />} />
        <Route path="/achats/paiements" element={<SupplierPaymentsPage />} />
        <Route path="/achats/paiements/nouveau" element={<SupplierPaymentFormPage />} />
        <Route path="/achats/dettes" element={<SupplierDebtsPage />} />
        <Route path="/achats/reglements" element={<SupplierSettlementsPage />} />
        {/* Stock screens (P1-T11) */}
        <Route path="/stock/mouvements" element={<MovementsPage />} />
        {/* Returnable boxes (P1-T14c) */}
        <Route path="/stock/caisses" element={<BoxesPage />} />
        <Route path="/stock/produits/:productId" element={<ProductStockPage />} />
        <Route path="/stock/lots/:batchId" element={<BatchStockPage />} />
        {/* Stock sections (P1-T09) */}
        <Route path="/stock/transferts" element={<TransfersPage />} />
        <Route path="/stock/transferts/nouveau" element={<TransferFormPage />} />
        <Route path="/stock/transferts/:transferId" element={<TransferDetailPage />} />
        <Route path="/stock/transferts/:transferId/modifier" element={<TransferEditPage />} />
        {/* Expenses and day labour (P5-T01, P5-T03) */}
        <Route path="/charges/nouvelle" element={<ExpenseFormPage />} />
        <Route path="/charges/calendrier" element={<DayLabourCalendarPage />} />
        <Route path="/charges/journaliers" element={<DayLabourersPage />} />
        <Route path="/charges/froid" element={<ColdRoomCostPage />} />
        <Route path="/charges/frais-generaux" element={<GeneralCostsPage />} />
        <Route path="/charges/:expenseId" element={<ExpenseDetailPage />} />
        <Route path="/charges/:expenseId/modifier" element={<ExpenseEditPage />} />
        {/* Stock sections (P1-T10) */}
        <Route path="/stock/pertes" element={<LossesPage />} />
        <Route path="/stock/pertes/nouvelle" element={<LossFormPage />} />
        <Route path="/stock/pertes/:lossId" element={<LossDetailPage />} />
        <Route path="/stock/inventaires" element={<CountsPage />} />
        <Route path="/stock/inventaires/:countId" element={<CountPage />} />
        <Route path="/demandes-site/:requestId" element={<WebRequestPage />} />
        {nav.flatMap((group) =>
          group.items
            .filter((item) => item.to !== "/")
            .map((item) => (
              <Route
                key={item.to}
                path={item.to}
                element={SCREENS[item.to] ?? <ComingSoon path={item.to} title={item.label} group={group.label} />}
              />
            )),
        )}
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Sprite />
      <Toaster position="bottom-right" />
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
