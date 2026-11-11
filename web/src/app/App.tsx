import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ApiError } from '../api/client'
import { ToastProvider } from '../components/Toast'
import { SignInPage } from '../features/auth/SignInPage'
import { ClientPickerDemo } from '../features/clients/ClientPickerDemo'
import { ClientProfilePage } from '../features/clients/ClientProfilePage'
import { ClientsPage } from '../features/clients/ClientsPage'
import { MergePage } from '../features/clients/MergePage'
import { TokenLinkPage } from '../features/auth/TokenLinkPage'
import { IntegrationsPage } from '../features/integrations/IntegrationsPage'
import { PayLinkPage } from '../features/billing/PayLinkPage'
import { AutomationsPage, RemindersPage } from '../features/engagement/AutomationPages'
import { CampaignDetailPage } from '../features/engagement/CampaignDetailPage'
import { CampaignsPage } from '../features/engagement/CampaignsPage'
import { EngagementLayout } from '../features/engagement/EngagementLayout'
import { SegmentsPage, TemplatesPage as MessageTemplatesPage } from '../features/engagement/LibraryPages'
import { MessageLogPage, SuppressionsPage } from '../features/engagement/MessagesPages'
import { PortalSettingsPage } from '../features/engagement/PortalPage'
import { UnsubscribePage } from '../features/engagement/UnsubscribePage'
import { PublicSignPage } from '../features/documents/PublicSignPage'
import { TemplateEditorPage } from '../features/documents/TemplateEditorPage'
import { TemplatesPage } from '../features/documents/TemplatesPage'
import { MembershipsPage } from '../features/memberships/MembershipsPage'
import { PackagesPage } from '../features/packages/PackagesPage'
import { PortalApp } from '../features/portal/PortalApp'
import { AuditLogPage } from '../features/platform/AuditLogPage'
import { DashboardPage } from '../features/platform/DashboardPage'
import { LocationsPage } from '../features/platform/LocationsPage'
import { RoleDetailPage } from '../features/platform/RoleDetailPage'
import { RolesPage } from '../features/platform/RolesPage'
import { StaffUserPage } from '../features/platform/StaffUserPage'
import { StaffUsersPage } from '../features/platform/StaffUsersPage'
import { TenantSettingsPage } from '../features/platform/TenantSettingsPage'
import { RentalSetupPage } from '../features/rentals/RentalSetupPage'
import { RentalsPage } from '../features/rentals/RentalsPage'
import { BasketPage } from '../features/programs/BasketPage'
import { BookingPolicyPage } from '../features/programs/BookingPolicyPage'
import { ProgramPage } from '../features/programs/ProgramPage'
import { ProgramsPage } from '../features/programs/ProgramsPage'
import { ResourcesPage } from '../features/resources/ResourcesPage'
import { CalendarPage } from '../features/scheduling/CalendarPage'
import { SetupPage } from '../features/scheduling/SetupPage'
import { AuthProvider } from '../lib/auth'
import { AgeingPage, AutopayPage } from '../features/billing/AutopayPage'
import { BillingLayout } from '../features/billing/BillingLayout'
import { ClientBillingLookupPage, ClientBillingPage } from '../features/billing/ClientBillingPage'
import { CouponsPage } from '../features/billing/CouponsPage'
import { InvoiceDocumentPage, InvoicePage } from '../features/billing/InvoicePage'
import { PaymentPage, ReceiptPage } from '../features/billing/PaymentPage'
import { BillingSettingsPage } from '../features/billing/SettingsPage'
import { SetupPage as BillingSetupPage } from '../features/billing/SetupPage'
import { WorkbenchPage } from '../features/billing/WorkbenchPage'
import { DrawersPage, EquipmentPage, PosReportsPage } from '../features/pos/OperationsPages'
import { ProductsPage } from '../features/pos/ProductsPage'
import { RegisterPage, RegisterPickerPage } from '../features/pos/RegisterPage'
import { PosReceiptPage, SaleDetailPage, SalesPage } from '../features/pos/SalesPage'
import { PosSetupPage } from '../features/pos/SetupPage'
import { PosLayout } from '../features/pos/shared'
import { CheckInPage } from '../features/access/CheckInPage'
import { HistoryPage as CheckInHistoryPage } from '../features/access/HistoryPage'
import { KioskPage } from '../features/access/KioskPage'
import { KioskSetupPage } from '../features/access/KioskSetupPage'
import { AppFrame } from './AppFrame'
import { RequireClient, RequirePermission, RequireStaff } from './guards'

// Opt in to v7 behaviour now so the upgrade is a version bump.
export const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      // 4xx answers are final; only retry what might be transient.
      queries: { retry: (n, e) => n < 2 && !(e instanceof ApiError && e.status < 500), refetchOnWindowFocus: false },
    },
  })
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignInPage />} />
      <Route path="/auth/magic-link" element={<TokenLinkPage purpose="magic-link" />} />
      <Route path="/auth/reset-password" element={<TokenLinkPage purpose="reset-password" />} />
      <Route path="/auth/accept-invite" element={<TokenLinkPage purpose="accept-invite" />} />
      <Route path="/pay" element={<PayLinkPage />} />
      <Route path="/sign" element={<PublicSignPage />} />
      <Route path="/unsubscribe" element={<UnsubscribePage />} />
      <Route path="/portal/*" element={<RequireClient><PortalApp /></RequireClient>} />
      <Route path="/kiosk" element={<KioskPage />} />
      <Route path="/billing/invoices/:id/document" element={<RequireStaff><RequirePermission permission="billing.invoice.read"><InvoiceDocumentPage /></RequirePermission></RequireStaff>} />
      <Route path="/billing/payments/:id/receipt" element={<RequireStaff><RequirePermission permission="billing.payment.read"><ReceiptPage /></RequirePermission></RequireStaff>} />
      <Route path="/pos/sales/:id/receipt" element={<RequireStaff><RequirePermission permission="pos.sale.read"><PosReceiptPage /></RequirePermission></RequireStaff>} />
      <Route element={<RequireStaff><AppFrame /></RequireStaff>}>
        <Route index element={<DashboardPage />} />
        <Route path="locations" element={<LocationsPage />} />
        <Route path="staff" element={<RequirePermission permission="platform.staff_user.read"><StaffUsersPage /></RequirePermission>} />
        <Route path="staff/:id" element={<RequirePermission permission="platform.staff_user.read"><StaffUserPage /></RequirePermission>} />
        <Route path="roles" element={<RequirePermission permission="platform.role.read"><RolesPage /></RequirePermission>} />
        <Route path="roles/:id" element={<RequirePermission permission="platform.role.read"><RoleDetailPage /></RequirePermission>} />
        <Route path="audit" element={<RequirePermission permission="platform.audit.read"><AuditLogPage /></RequirePermission>} />
        <Route path="integrations" element={<IntegrationsPage />} />
        <Route path="settings" element={<RequirePermission permission="platform.tenant.update"><TenantSettingsPage /></RequirePermission>} />
        <Route path="billing" element={<RequirePermission permission="billing.charge.read"><BillingLayout /></RequirePermission>}>
          <Route index element={<WorkbenchPage />} />
          <Route path="clients" element={<ClientBillingLookupPage />} />
          <Route path="clients/:clientId" element={<ClientBillingPage />} />
          <Route path="invoices/:id" element={<RequirePermission permission="billing.invoice.read"><InvoicePage /></RequirePermission>} />
          <Route path="payments/:id" element={<RequirePermission permission="billing.payment.read"><PaymentPage /></RequirePermission>} />
          <Route path="autopay" element={<RequirePermission permission="billing.payment.read"><AutopayPage /></RequirePermission>} />
          <Route path="receivables" element={<RequirePermission permission="billing.invoice.read"><AgeingPage /></RequirePermission>} />
          <Route path="coupons" element={<CouponsPage />} />
          <Route path="setup" element={<BillingSetupPage />} />
          <Route path="settings" element={<RequirePermission permission="billing.settings.manage"><BillingSettingsPage /></RequirePermission>} />
        </Route>
        <Route path="pos" element={<RequirePermission permission="pos.sale.read"><PosLayout /></RequirePermission>}>
          <Route index element={<RequirePermission permission="pos.sale.create"><RegisterPickerPage /></RequirePermission>} />
          <Route path="register/:registerId" element={<RequirePermission permission="pos.sale.create"><RegisterPage /></RequirePermission>} />
          <Route path="sales" element={<SalesPage />} />
          <Route path="sales/:id" element={<SaleDetailPage />} />
          <Route path="products" element={<ProductsPage />} />
          <Route path="equipment" element={<RequirePermission permission="pos.equipment.rent"><EquipmentPage /></RequirePermission>} />
          <Route path="drawers" element={<RequirePermission permission="pos.drawer.operate"><DrawersPage /></RequirePermission>} />
          <Route path="reports" element={<PosReportsPage />} />
          <Route path="setup" element={<RequirePermission permission="pos.register.manage"><PosSetupPage /></RequirePermission>} />
        </Route>
        <Route path="engagement" element={<RequirePermission permission="engagement.campaign.read"><EngagementLayout /></RequirePermission>}>
          <Route index element={<CampaignsPage />} />
          <Route path="campaigns/:id" element={<CampaignDetailPage />} />
          <Route path="templates" element={<MessageTemplatesPage />} />
          <Route path="segments" element={<SegmentsPage />} />
          <Route path="messages" element={<MessageLogPage />} />
          <Route path="suppressions" element={<RequirePermission permission="engagement.suppression.manage"><SuppressionsPage /></RequirePermission>} />
          <Route path="automations" element={<RequirePermission permission="engagement.automation.manage"><AutomationsPage /></RequirePermission>} />
          <Route path="reminders" element={<RequirePermission permission="engagement.notification_rule.manage"><RemindersPage /></RequirePermission>} />
          <Route path="portal" element={<PortalSettingsPage />} />
        </Route>
        <Route path="clients" element={<RequirePermission permission="clients.client.read"><ClientsPage /></RequirePermission>} />
        <Route path="clients/merge" element={<RequirePermission permission="clients.client.merge"><MergePage /></RequirePermission>} />
        <Route path="clients/:id" element={<RequirePermission permission="clients.client.read"><ClientProfilePage /></RequirePermission>} />
        <Route path="documents" element={<RequirePermission permission="documents.template.manage"><TemplatesPage /></RequirePermission>} />
        <Route path="documents/:id" element={<RequirePermission permission="documents.template.manage"><TemplateEditorPage /></RequirePermission>} />
        <Route path="memberships" element={<RequirePermission permission="memberships.contract.read"><MembershipsPage /></RequirePermission>} />
        <Route path="packages" element={<RequirePermission permission="packages.package.read"><PackagesPage /></RequirePermission>} />
        <Route path="schedule" element={<RequirePermission permission="scheduling.booking.read"><CalendarPage /></RequirePermission>} />
        <Route path="resources" element={<ResourcesPage />} />
        <Route path="scheduling/setup" element={<SetupPage />} />
        <Route path="rentals" element={<RequirePermission permission="scheduling.booking.read"><RentalsPage /></RequirePermission>} />
        <Route path="rentals/setup" element={<RentalSetupPage />} />
        <Route path="programs" element={<RequirePermission permission="programs.registration.read"><ProgramsPage /></RequirePermission>} />
        <Route path="programs/register" element={<RequirePermission permission="programs.registration.create"><BasketPage /></RequirePermission>} />
        <Route path="programs/booking-policies" element={<RequirePermission permission="programs.registration_config.manage"><BookingPolicyPage /></RequirePermission>} />
        <Route path="programs/:id" element={<RequirePermission permission="programs.registration.read"><ProgramPage /></RequirePermission>} />
        <Route path="check-in" element={<RequirePermission permission="access.checkin.create"><CheckInPage /></RequirePermission>} />
        <Route path="check-in/history" element={<RequirePermission permission="access.checkin.read"><CheckInHistoryPage /></RequirePermission>} />
        <Route path="check-in/kiosks" element={<KioskSetupPage />} />
        {import.meta.env.DEV && (
          <Route path="dev/client-picker" element={<RequirePermission permission="clients.client.read"><ClientPickerDemo /></RequirePermission>} />
        )}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export function App() {
  const [queryClient] = useState(makeQueryClient)
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <BrowserRouter future={ROUTER_FUTURE}>
            <AppRoutes />
          </BrowserRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
