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
import { PublicSignPage } from '../features/documents/PublicSignPage'
import { TemplateEditorPage } from '../features/documents/TemplateEditorPage'
import { TemplatesPage } from '../features/documents/TemplatesPage'
import { PortalHome } from '../features/portal/PortalHome'
import { AuditLogPage } from '../features/platform/AuditLogPage'
import { DashboardPage } from '../features/platform/DashboardPage'
import { LocationsPage } from '../features/platform/LocationsPage'
import { RoleDetailPage } from '../features/platform/RoleDetailPage'
import { RolesPage } from '../features/platform/RolesPage'
import { StaffUserPage } from '../features/platform/StaffUserPage'
import { StaffUsersPage } from '../features/platform/StaffUsersPage'
import { TenantSettingsPage } from '../features/platform/TenantSettingsPage'
import { AuthProvider } from '../lib/auth'
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
      <Route path="/sign" element={<PublicSignPage />} />
      <Route path="/portal/*" element={<RequireClient><PortalHome /></RequireClient>} />
      <Route element={<RequireStaff><AppFrame /></RequireStaff>}>
        <Route index element={<DashboardPage />} />
        <Route path="locations" element={<LocationsPage />} />
        <Route path="staff" element={<RequirePermission permission="platform.staff_user.read"><StaffUsersPage /></RequirePermission>} />
        <Route path="staff/:id" element={<RequirePermission permission="platform.staff_user.read"><StaffUserPage /></RequirePermission>} />
        <Route path="roles" element={<RequirePermission permission="platform.role.read"><RolesPage /></RequirePermission>} />
        <Route path="roles/:id" element={<RequirePermission permission="platform.role.read"><RoleDetailPage /></RequirePermission>} />
        <Route path="audit" element={<RequirePermission permission="platform.audit.read"><AuditLogPage /></RequirePermission>} />
        <Route path="settings" element={<RequirePermission permission="platform.tenant.update"><TenantSettingsPage /></RequirePermission>} />
        <Route path="clients" element={<RequirePermission permission="clients.client.read"><ClientsPage /></RequirePermission>} />
        <Route path="clients/merge" element={<RequirePermission permission="clients.client.merge"><MergePage /></RequirePermission>} />
        <Route path="clients/:id" element={<RequirePermission permission="clients.client.read"><ClientProfilePage /></RequirePermission>} />
        <Route path="documents" element={<RequirePermission permission="documents.template.manage"><TemplatesPage /></RequirePermission>} />
        <Route path="documents/:id" element={<RequirePermission permission="documents.template.manage"><TemplateEditorPage /></RequirePermission>} />
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
