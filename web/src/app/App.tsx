import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ApiError } from '../api/client'
import { ToastProvider } from '../components/Toast'
import { SignInPage } from '../features/auth/SignInPage'
import { StepUpDialog } from '../features/auth/StepUpDialog'
import { ClientPickerDemo } from '../features/clients/ClientPickerDemo'
import { AgeChecksPage } from '../features/clients/AgeChecks'
import { ClientProfilePage } from '../features/clients/ClientProfilePage'
import { ClientsPage } from '../features/clients/ClientsPage'
import { MergePage } from '../features/clients/MergePage'
import { TokenLinkPage } from '../features/auth/TokenLinkPage'
import { OidcCallbackPage, OidcLinkPage } from '../features/auth/oidc'
import { IntegrationsPage } from '../features/integrations/IntegrationsPage'
import { QuickBooksCallbackPage } from '../features/integrations/QuickBooksCallbackPage'
import { PayLinkPage } from '../features/billing/PayLinkPage'
import { AppConfigPage } from '../features/engagement/AppConfigPage'
import { AutomationsPage, RemindersPage } from '../features/engagement/AutomationPages'
import { CampaignDetailPage } from '../features/engagement/CampaignDetailPage'
import { CampaignsPage } from '../features/engagement/CampaignsPage'
import { EngagementLayout } from '../features/engagement/EngagementLayout'
import { SegmentsPage, TemplatesPage as MessageTemplatesPage } from '../features/engagement/LibraryPages'
import { MEMBER_CONTENT_KEYS, MemberContentPage } from '../features/engagement/MemberContentPage'
import { MessageLogPage, SuppressionsPage } from '../features/engagement/MessagesPages'
import { PortalSettingsPage } from '../features/engagement/PortalPage'
import { UnsubscribePage } from '../features/engagement/UnsubscribePage'
import { PublicSignPage } from '../features/documents/PublicSignPage'
import { TemplateEditorPage } from '../features/documents/TemplateEditorPage'
import { TemplatesPage } from '../features/documents/TemplatesPage'
import { ScoresPage, StatsPage, VenuesPage } from '../features/leagues/depth'
import { LeaguePage, LeaguesPage } from '../features/leagues/LeaguesPage'
import { LeagueBoardPage, PublicLeaguesPage } from '../features/leagues/PublicLeaguesPage'
import { PublicSchedulePage } from '../features/integrations/PublicSchedulePage'
import { LeaguePostsPage, LeagueSitePage } from '../features/leagues/SitePages'
import { MembershipsPage } from '../features/memberships/MembershipsPage'
import { PackagesPage } from '../features/packages/PackagesPage'
import { PublicDirectLinkPage } from '../features/scheduling/sharing'
import { PortalApp } from '../features/portal/PortalApp'
import { PublicProgressPage } from '../features/portal/PublicProgressPage'
import { AuditLogPage } from '../features/platform/AuditLogPage'
import { DashboardPage } from '../features/platform/DashboardPage'
import { WhatsNewPage } from '../features/platform/WhatsNewPage'
import { LocationsPage } from '../features/platform/LocationsPage'
import { RoleDetailPage } from '../features/platform/RoleDetailPage'
import { RolesPage } from '../features/platform/RolesPage'
import { StaffUserPage } from '../features/platform/StaffUserPage'
import { StaffUsersPage } from '../features/platform/StaffUsersPage'
import { PrivacyPage } from '../features/platform/PrivacyPage'
import { SecuritySettingsPage } from '../features/platform/SecuritySettingsPage'
import { PlanUsagePage } from '../features/platform/PlanUsagePage'
import { ImportDataPage } from '../features/imports/ImportDataPage'
import { SupportPage } from '../features/platform/SupportPage'
import { AccountSecurityPage } from '../features/platform/AccountSecurityPage'
import { TenantSettingsPage } from '../features/platform/TenantSettingsPage'
import { RentalSetupPage } from '../features/rentals/RentalSetupPage'
import { RentalsPage } from '../features/rentals/RentalsPage'
import { LockersPage } from '../features/lockers/LockersPage'
import { BasketPage } from '../features/programs/BasketPage'
import { BookingPolicyPage } from '../features/programs/BookingPolicyPage'
import { ProgramPage } from '../features/programs/ProgramPage'
import { ProgramsPage } from '../features/programs/ProgramsPage'
import { FormPage } from '../features/programs/FormPage'
import { FormsPage } from '../features/programs/FormsPage'
import { ProgramSetupPage } from '../features/programs/groupTools'
import { PublicFormPage } from '../features/programs/PublicFormPage'
import { ResourcesPage } from '../features/resources/ResourcesPage'
import { CalendarPage } from '../features/scheduling/CalendarPage'
import { SetupPage } from '../features/scheduling/SetupPage'
import { AuthProvider } from '../lib/auth'
import { AgeingPage, AutopayPage } from '../features/billing/AutopayPage'
import { BillingLayout } from '../features/billing/BillingLayout'
import { ClientBillingLookupPage, ClientBillingPage } from '../features/billing/ClientBillingPage'
import { CollectionsPage } from '../features/billing/CollectionsPage'
import { CouponsPage } from '../features/billing/CouponsPage'
import { CatalogPage } from '../features/billing/CatalogPage'
import { InvoiceDocumentPage, InvoicePage } from '../features/billing/InvoicePage'
import { ExpiringCardsPage, NoticesPage } from '../features/billing/NoticesPage'
import { PaymentPage, ReceiptPage } from '../features/billing/PaymentPage'
import { BillingSettingsPage } from '../features/billing/SettingsPage'
import { StatementsPage } from '../features/billing/StatementsPage'
import { SetupPage as BillingSetupPage } from '../features/billing/SetupPage'
import { WorkbenchPage } from '../features/billing/WorkbenchPage'
import { EXPORT_KEY, RUN_KEYS } from '../features/reporting/queries'
import { FacilityApp } from '../features/entry/FacilityApp'
import { ReportRunRoute } from '../features/reporting/ReportRunPage'
import { ReportsPage } from '../features/reporting/ReportsPage'
import { ExportJobPage } from '../features/reporting/ExportJobPage'
import { DrawersPage, EquipmentPage, PosReportsPage } from '../features/pos/OperationsPages'
import { ProductsPage } from '../features/pos/ProductsPage'
import { RegisterPage, RegisterPickerPage } from '../features/pos/RegisterPage'
import { PosReceiptPage, SaleDetailPage, SalesPage } from '../features/pos/SalesPage'
import { PosSetupPage } from '../features/pos/SetupPage'
import { AssessmentSetupPage } from '../features/assessments/AssessmentSetupPage'
import { ClockPage } from '../features/staff/ClockPage'
import { CoachSharePage } from '../features/staff/CoachSharePage'
import { MyEarningsPage } from '../features/staff/MyEarningsPage'
import { PayeesPage } from '../features/staff/PayeesPage'
import { PayrollPage } from '../features/staff/PayrollPage'
import { ShiftsPage } from '../features/staff/ShiftsPage'
import { StaffSetupPage } from '../features/staff/StaffSetupPage'
import { StaffTimeLayout } from '../features/staff/shared'
import { TimeEntriesPage } from '../features/staff/TimeEntriesPage'
import { PosLayout } from '../features/pos/shared'
import { CheckInPage } from '../features/access/CheckInPage'
import { HistoryPage as CheckInHistoryPage } from '../features/access/HistoryPage'
import { KioskPage } from '../features/access/KioskPage'
import { KioskSetupPage } from '../features/access/KioskSetupPage'
import { AccessRulesPage } from '../features/access/AccessRulesPage'
import { BuildingPage } from '../features/access/BuildingPage'
import { DeskSetupPage, MemberCardPage, OccupancyPage } from '../features/access/DeskPages'
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

/** True inside an iframe. The proxy lets other sites frame the public league pages, the TV board and the public
 * schedule page only (owner
 * decision 2026-11-13, infra/proxy/Caddyfile `@embeddable`); this keeps every other screen out of a frame too,
 * since the app is one document and any route can load behind those paths. */
export function isFramed(): boolean {
  return window.top !== window.self
}

/** What a framed app may render: the embeddable public league and schedule routes, and a refusal for everything else. */
export function FramedRoutes() {
  return (
    <Routes>
      <Route path="/leagues/public" element={<PublicLeaguesPage />} />
      <Route path="/leagues/public/:id" element={<PublicLeaguesPage />} />
      <Route path="/leagues/board/:locationId" element={<LeagueBoardPage />} />
      <Route path="/schedule/public/:locationId" element={<PublicSchedulePage />} />
      <Route path="*" element={<main className="p-6"><h1 className="text-lg font-semibold">This page cannot be shown inside another site</h1><a className="text-primary hover:underline" href={window.location.href} target="_top">Open it in its own window</a></main>} />
    </Routes>
  )
}

export function AppRoutes() {
  if (isFramed()) return <FramedRoutes />
  return (
    <Routes>
      <Route path="/sign-in" element={<SignInPage />} />
      <Route path="/auth/magic-link" element={<TokenLinkPage purpose="magic-link" />} />
      <Route path="/auth/reset-password" element={<TokenLinkPage purpose="reset-password" />} />
      <Route path="/auth/accept-invite" element={<TokenLinkPage purpose="accept-invite" />} />
      <Route path="/auth/oidc/callback" element={<OidcCallbackPage />} />
      <Route path="/auth/oidc/link" element={<OidcLinkPage />} />
      <Route path="/pay" element={<PayLinkPage />} />
      <Route path="/progress" element={<PublicProgressPage />} />
      <Route path="/sign" element={<PublicSignPage />} />
      <Route path="/direct-link" element={<PublicDirectLinkPage />} />
      <Route path="/unsubscribe" element={<UnsubscribePage />} />
      <Route path="/leagues/public" element={<PublicLeaguesPage />} />
      <Route path="/forms/:id" element={<PublicFormPage />} />
      <Route path="/leagues/public/:id" element={<PublicLeaguesPage />} />
      <Route path="/f/:slug/*" element={<FacilityApp />} />
      <Route path="/leagues/board/:locationId" element={<LeagueBoardPage />} />
      <Route path="/schedule/public/:locationId" element={<PublicSchedulePage />} />
      <Route path="/portal/*" element={<RequireClient><PortalApp /></RequireClient>} />
      <Route path="/kiosk" element={<KioskPage />} />
      <Route path="/billing/invoices/:id/document" element={<RequireStaff><RequirePermission permission="billing.invoice.read"><InvoiceDocumentPage /></RequirePermission></RequireStaff>} />
      <Route path="/billing/payments/:id/receipt" element={<RequireStaff><RequirePermission permission="billing.payment.read"><ReceiptPage /></RequirePermission></RequireStaff>} />
      <Route path="/pos/sales/:id/receipt" element={<RequireStaff><RequirePermission permission="pos.sale.read"><PosReceiptPage /></RequirePermission></RequireStaff>} />
      <Route element={<RequireStaff><AppFrame /></RequireStaff>}>
        <Route index element={<DashboardPage />} />
        <Route path="locations" element={<LocationsPage />} />
        <Route path="whats-new" element={<WhatsNewPage />} />
        <Route path="staff" element={<RequirePermission permission="platform.staff_user.read"><StaffUsersPage /></RequirePermission>} />
        <Route path="staff/:id" element={<RequirePermission permission="platform.staff_user.read"><StaffUserPage /></RequirePermission>} />
        <Route path="roles" element={<RequirePermission permission="platform.role.read"><RolesPage /></RequirePermission>} />
        <Route path="roles/:id" element={<RequirePermission permission="platform.role.read"><RoleDetailPage /></RequirePermission>} />
        <Route path="audit" element={<RequirePermission permission="platform.audit.read"><AuditLogPage /></RequirePermission>} />
        <Route path="integrations" element={<IntegrationsPage />} />
        <Route path="integrations/quickbooks/callback" element={<RequirePermission permission="integrations.connection.manage"><QuickBooksCallbackPage /></RequirePermission>} />
        <Route path="settings" element={<RequirePermission permission="platform.tenant.update"><TenantSettingsPage /></RequirePermission>} />
        <Route path="account/security" element={<AccountSecurityPage />} />
        <Route path="settings/security" element={<RequirePermission permission="platform.security.manage"><SecuritySettingsPage /></RequirePermission>} />
        <Route path="settings/plan" element={<RequirePermission permission="platform.tenant.update"><PlanUsagePage /></RequirePermission>} />
        <Route path="settings/import" element={<RequirePermission permission="platform.import_job.read"><ImportDataPage /></RequirePermission>} />
        <Route path="settings/privacy" element={<RequirePermission permission={['platform.security.manage', 'platform.tenant.export']}><PrivacyPage /></RequirePermission>} />
        <Route path="support" element={<RequirePermission permission="platform.support_request.create"><SupportPage /></RequirePermission>} />
        <Route path="billing" element={<RequirePermission permission="billing.charge.read"><BillingLayout /></RequirePermission>}>
          <Route index element={<WorkbenchPage />} />
          <Route path="clients" element={<ClientBillingLookupPage />} />
          <Route path="clients/:clientId" element={<ClientBillingPage />} />
          <Route path="invoices/:id" element={<RequirePermission permission="billing.invoice.read"><InvoicePage /></RequirePermission>} />
          <Route path="payments/:id" element={<RequirePermission permission="billing.payment.read"><PaymentPage /></RequirePermission>} />
          <Route path="autopay" element={<RequirePermission permission="billing.payment.read"><AutopayPage /></RequirePermission>} />
          <Route path="receivables" element={<RequirePermission permission="billing.invoice.read"><AgeingPage /></RequirePermission>} />
          <Route path="statements" element={<RequirePermission permission="billing.statement.send"><StatementsPage /></RequirePermission>} />
          <Route path="collections" element={<RequirePermission permission="billing.collections.read"><CollectionsPage /></RequirePermission>} />
          <Route path="notices" element={<RequirePermission permission="billing.invoice.read"><NoticesPage /></RequirePermission>} />
          <Route path="expiring-cards" element={<RequirePermission permission="billing.payment_method.read"><ExpiringCardsPage /></RequirePermission>} />
          <Route path="coupons" element={<CouponsPage />} />
          <Route path="catalog" element={<CatalogPage />} />
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
          <Route path="reports" element={<RequirePermission permission="reporting.pos.run"><PosReportsPage /></RequirePermission>} />
          <Route path="setup" element={<RequirePermission permission="pos.register.manage"><PosSetupPage /></RequirePermission>} />
        </Route>
        <Route path="reports" element={<RequirePermission permission={RUN_KEYS}><ReportsPage /></RequirePermission>} />
        <Route path="reports/exports/:exportJobId" element={<RequirePermission permission={EXPORT_KEY}><ExportJobPage /></RequirePermission>} />
        <Route path="reports/:reportKey" element={<RequirePermission permission={RUN_KEYS}><ReportRunRoute /></RequirePermission>} />
        <Route path="staff-time" element={<StaffTimeLayout />}>
          <Route index element={<RequirePermission permission="staff.time_entry.punch"><ClockPage /></RequirePermission>} />
          <Route path="entries" element={<RequirePermission permission="staff.time_entry.read"><TimeEntriesPage /></RequirePermission>} />
          <Route path="shifts" element={<RequirePermission permission="staff.shift.manage"><ShiftsPage /></RequirePermission>} />
          <Route path="payees" element={<RequirePermission permission="resources.resource.manage"><PayeesPage /></RequirePermission>} />
          <Route path="payroll" element={<RequirePermission permission="staff.payroll_run.create"><PayrollPage /></RequirePermission>} />
          <Route path="coach-share" element={<RequirePermission permission="staff.coach_payout.create"><CoachSharePage /></RequirePermission>} />
          <Route path="my-earnings" element={<RequirePermission permission="staff.coach_payout.read"><MyEarningsPage /></RequirePermission>} />
          <Route path="setup" element={<RequirePermission permission="staff.time_entry.manage"><StaffSetupPage /></RequirePermission>} />
        </Route>
        <Route path="assessments/setup" element={<RequirePermission permission="assessments.definition.manage"><AssessmentSetupPage /></RequirePermission>} />
        {/* The member app pages have their own keys, so the area opens for those too; campaign pages keep campaign.read. */}
        <Route path="engagement" element={<RequirePermission permission={['engagement.campaign.read', 'engagement.portal_settings.manage', ...MEMBER_CONTENT_KEYS]}><EngagementLayout /></RequirePermission>}>
          <Route index element={<RequirePermission permission="engagement.campaign.read"><CampaignsPage /></RequirePermission>} />
          <Route path="campaigns/:id" element={<RequirePermission permission="engagement.campaign.read"><CampaignDetailPage /></RequirePermission>} />
          <Route path="templates" element={<RequirePermission permission="engagement.campaign.read"><MessageTemplatesPage /></RequirePermission>} />
          <Route path="segments" element={<RequirePermission permission="engagement.campaign.read"><SegmentsPage /></RequirePermission>} />
          <Route path="messages" element={<RequirePermission permission="engagement.campaign.read"><MessageLogPage /></RequirePermission>} />
          <Route path="suppressions" element={<RequirePermission permission="engagement.suppression.manage"><SuppressionsPage /></RequirePermission>} />
          <Route path="automations" element={<RequirePermission permission="engagement.automation.manage"><AutomationsPage /></RequirePermission>} />
          <Route path="reminders" element={<RequirePermission permission="engagement.notification_rule.manage"><RemindersPage /></RequirePermission>} />
          <Route path="portal" element={<RequirePermission permission={['engagement.portal_settings.manage', 'engagement.app_content.manage']}><PortalSettingsPage /></RequirePermission>} />
          <Route path="app" element={<RequirePermission permission="engagement.app_content.manage"><AppConfigPage /></RequirePermission>} />
          <Route path="app-content" element={<RequirePermission permission={MEMBER_CONTENT_KEYS}><MemberContentPage /></RequirePermission>} />
        </Route>
        <Route path="clients" element={<RequirePermission permission="clients.client.read"><ClientsPage /></RequirePermission>} />
        <Route path="clients/merge" element={<RequirePermission permission="clients.client.merge"><MergePage /></RequirePermission>} />
        <Route path="clients/age-checks" element={<RequirePermission permission="clients.client.confirm_age"><AgeChecksPage /></RequirePermission>} />
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
        <Route path="lockers" element={<RequirePermission permission={['rentals.locker_rental.manage', 'resources.locker.manage', 'resources.padlock.reveal_combination']}><LockersPage /></RequirePermission>} />
        <Route path="programs" element={<RequirePermission permission="programs.registration.read"><ProgramsPage /></RequirePermission>} />
        <Route path="programs/register" element={<RequirePermission permission="programs.registration.create"><BasketPage /></RequirePermission>} />
        <Route path="programs/booking-policies" element={<RequirePermission permission={['engagement.portal_settings.manage', 'programs.registration_config.manage']}><BookingPolicyPage /></RequirePermission>} />
        <Route path="programs/forms" element={<RequirePermission permission="programs.form.manage"><FormsPage /></RequirePermission>} />
        <Route path="programs/forms/:id" element={<RequirePermission permission="programs.form.manage"><FormPage /></RequirePermission>} />
        <Route path="programs/setup" element={<RequirePermission permission="programs.program.manage"><ProgramSetupPage /></RequirePermission>} />
        <Route path="programs/:id" element={<RequirePermission permission="programs.registration.read"><ProgramPage /></RequirePermission>} />
        <Route path="check-in" element={<RequirePermission permission="access.checkin.create"><CheckInPage /></RequirePermission>} />
        <Route path="check-in/history" element={<RequirePermission permission="access.checkin.read"><CheckInHistoryPage /></RequirePermission>} />
        <Route path="check-in/kiosks" element={<KioskSetupPage />} />
        <Route path="check-in/access" element={<AccessRulesPage />} />
        <Route path="check-in/building" element={<RequirePermission permission="access.checkin.read"><BuildingPage /></RequirePermission>} />
        <Route path="check-in/occupancy" element={<RequirePermission permission="access.checkin.read"><OccupancyPage /></RequirePermission>} />
        <Route path="check-in/desk-setup" element={<DeskSetupPage />} />
        <Route path="check-in/card/:id" element={<RequirePermission permission="access.credential.assign"><MemberCardPage /></RequirePermission>} />
        <Route path="leagues" element={<RequirePermission permission="leagues.competition.manage"><LeaguesPage /></RequirePermission>} />
        <Route path="leagues/venues" element={<RequirePermission permission="leagues.competition.manage"><VenuesPage /></RequirePermission>} />
        <Route path="leagues/stats" element={<RequirePermission permission="leagues.competition.manage"><StatsPage /></RequirePermission>} />
        <Route path="leagues/site" element={<RequirePermission permission="leagues.public_site.manage"><LeagueSitePage /></RequirePermission>} />
        <Route path="leagues/posts" element={<RequirePermission permission="leagues.classified.moderate"><LeaguePostsPage /></RequirePermission>} />
        <Route path="leagues/scores" element={<RequirePermission permission="leagues.result.enter"><ScoresPage /></RequirePermission>} />
        <Route path="leagues/:id" element={<RequirePermission permission="leagues.competition.manage"><LeaguePage /></RequirePermission>} />
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
          <StepUpDialog />
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
