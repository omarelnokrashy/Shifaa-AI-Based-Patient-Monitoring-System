/**
 * App.jsx — root router.
 *
 * Route structure:
 *   /login                     → LoginPage (public)
 *   /                          → RootRedirect (role-aware redirect)
 *   /doctor/*                  → NavShell + doctor routes (requires role=doctor)
 *   /nurse/*                   → NavShell + nurse routes  (requires role=nurse)
 *   /admin/*                   → NavShell + admin routes  (requires role=admin)
 *
 * RoleGuard is a wrapper component that:
 *   1. Redirects to /login if no token
 *   2. Redirects to the correct role's dashboard if the role doesn't match
 *   3. Renders the child route otherwise
 *
 * Nurse patient detail reuses the doctor's PatientDetailPage in read-only mode
 * (no chat mode-switch, no ECG analysis button).
 */
import { Routes, Route, Navigate, Outlet } from 'react-router-dom'
import useAuthStore from './store/authStore'

// Layout
import NavShell from './components/layout/NavShell'

// Auth
import LoginPage from './pages/auth/LoginPage'

// Doctor
import DoctorDashboard    from './pages/doctor/DoctorDashboard'
import PatientListPage    from './pages/doctor/PatientListPage'
import PatientDetailPage  from './pages/doctor/PatientDetailPage'
import LiveMonitoringPage from './pages/doctor/LiveMonitoringPage'

// Nurse
import NurseDashboard from './pages/nurse/NurseDashboard'

// Admin
import AdminDashboard    from './pages/admin/AdminDashboard'
import UserManagementPage from './pages/admin/UserManagementPage'

// ── Role guard ────────────────────────────────────────────────────────────────
function RoleGuard({ allowedRole }) {
  const user = useAuthStore((s) => s.user)
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== allowedRole) {
    // Redirect to the correct home for their actual role
    const homes = { doctor: '/doctor/dashboard', nurse: '/nurse/dashboard', admin: '/admin/dashboard' }
    return <Navigate to={homes[user.role] || '/login'} replace />
  }
  return <Outlet />
}

// ── Root redirect ──────────────────────────────────────────────────────────────
function RootRedirect() {
  const user = useAuthStore((s) => s.user)
  if (!user) return <Navigate to="/login" replace />
  const homes = { doctor: '/doctor/dashboard', nurse: '/nurse/dashboard', admin: '/admin/dashboard' }
  return <Navigate to={homes[user.role] || '/login'} replace />
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/"      element={<RootRedirect />} />

      {/* ── Doctor routes ───────────────────────────────────────────────── */}
      <Route element={<RoleGuard allowedRole="doctor" />}>
        <Route element={<NavShell />}>
          <Route path="/doctor/dashboard"            element={<DoctorDashboard />} />
          <Route path="/doctor/patients"             element={<PatientListPage />} />
          <Route path="/doctor/patients/:id"         element={<PatientDetailPage />} />
          <Route path="/doctor/monitoring"           element={<LiveMonitoringPage />} />
        </Route>
      </Route>

      {/* ── Nurse routes ────────────────────────────────────────────────── */}
      <Route element={<RoleGuard allowedRole="nurse" />}>
        <Route element={<NavShell />}>
          <Route path="/nurse/dashboard"   element={<NurseDashboard />} />
          {/* Reuse patient list + detail — the read-only behavior is
              enforced by the API (nurses can't run ECG analysis, etc.) */}
          <Route path="/nurse/patients"    element={<PatientListPage />} />
          <Route path="/nurse/patients/:id" element={<PatientDetailPage />} />
        </Route>
      </Route>

      {/* ── Admin routes ─────────────────────────────────────────────────── */}
      <Route element={<RoleGuard allowedRole="admin" />}>
        <Route element={<NavShell />}>
          <Route path="/admin/dashboard" element={<AdminDashboard />} />
          <Route path="/admin/users"     element={<UserManagementPage />} />
        </Route>
      </Route>

      {/* 404 fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
