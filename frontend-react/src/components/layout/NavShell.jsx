/**
 * NavShell — the persistent app chrome.
 *
 * Renders a dark navy sidebar with role-aware navigation items and a top-bar
 * for mobile (collapses the sidebar on small screens). The main <Outlet />
 * renders the current screen in the content area.
 *
 * Navigation items are filtered by role so doctors, nurses, and admins each
 * see only the sections relevant to them — no separate apps, one shell.
 */
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import {
  LayoutDashboard, Users, Activity, Bell, Settings,
  HeartPulse, LogOut, Menu, X, ChevronRight,
} from 'lucide-react'
import useAuthStore from '../../store/authStore'
import useAlertsStore from '../../store/alertsStore'
import { useAlertsWS } from '../../hooks/useAlertsWS'

// ── Nav items definitions ─────────────────────────────────────────────────────
const NAV_ITEMS = {
  doctor: [
    { to: '/doctor/dashboard',  label: 'Dashboard',   Icon: LayoutDashboard },
    { to: '/doctor/patients',   label: 'Patients',    Icon: Users },
    { to: '/doctor/monitoring', label: 'Live Monitor',Icon: Activity },
  ],
  nurse: [
    { to: '/nurse/dashboard', label: 'Dashboard', Icon: LayoutDashboard },
    { to: '/nurse/patients',  label: 'Patients',  Icon: Users },
  ],
  admin: [
    { to: '/admin/dashboard', label: 'System',       Icon: Settings },
    { to: '/admin/users',     label: 'Users',         Icon: Users },
  ],
}

export default function NavShell() {
  useAlertsWS()   // Start the global alert WebSocket connection

  const user       = useAuthStore((s) => s.user)
  const logout     = useAuthStore((s) => s.logout)
  const unread     = useAlertsStore((s) => s.unread)
  const clearUnread = useAlertsStore((s) => s.clearUnread)
  const navigate   = useNavigate()
  const [collapsed, setCollapsed] = useState(false)

  const navItems = NAV_ITEMS[user?.role] || []

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="flex h-screen bg-navy-50 overflow-hidden">
      {/* ── Sidebar ────────────────────────────────────────────────────── */}
      <aside
        className={clsx(
          'flex flex-col bg-navy-950 shadow-sidebar transition-all duration-300 ease-in-out shrink-0',
          collapsed ? 'w-16' : 'w-60',
        )}
      >
        {/* Logo / brand */}
        <div className="flex items-center gap-3 px-4 py-5 border-b border-navy-800">
          <div className="w-8 h-8 rounded-lg bg-teal-600 flex items-center justify-center shrink-0">
            <HeartPulse size={18} className="text-white" />
          </div>
          {!collapsed && (
            <div className="overflow-hidden">
              <p className="font-heading font-bold text-white text-sm leading-tight truncate">MedMonitor</p>
              <p className="text-navy-400 text-xs truncate capitalize">{user?.role} portal</p>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-1">
          {navItems.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => clsx('nav-item', isActive && 'active')}
              title={collapsed ? label : undefined}
            >
              <Icon size={18} className="shrink-0" />
              {!collapsed && <span className="truncate">{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* Bottom: alerts + user + collapse */}
        <div className="border-t border-navy-800 px-2 py-3 space-y-1">
          {/* Alerts bell (doctor/nurse) */}
          {user?.role !== 'admin' && (
            <button
              onClick={() => { navigate(`/${user?.role}/dashboard`); clearUnread() }}
              className={clsx('nav-item w-full relative', collapsed && 'justify-center')}
              title={collapsed ? 'Alerts' : undefined}
            >
              <Bell size={18} className="shrink-0" />
              {!collapsed && <span>Alerts</span>}
              {unread > 0 && (
                <span className="absolute top-1.5 left-5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center">
                  {unread > 99 ? '99+' : unread}
                </span>
              )}
            </button>
          )}

          {/* User info */}
          {!collapsed && (
            <div className="px-3 py-2 rounded-lg bg-navy-900 mt-1">
              <p className="text-white text-xs font-medium truncate">{user?.name}</p>
              <p className="text-navy-400 text-[11px] capitalize">{user?.role}</p>
            </div>
          )}

          {/* Logout */}
          <button
            onClick={handleLogout}
            className={clsx('nav-item w-full text-red-400 hover:text-red-300 hover:bg-red-900/20', collapsed && 'justify-center')}
            title={collapsed ? 'Logout' : undefined}
          >
            <LogOut size={18} className="shrink-0" />
            {!collapsed && <span>Logout</span>}
          </button>

          {/* Collapse toggle */}
          <button
            onClick={() => setCollapsed((c) => !c)}
            className={clsx('nav-item w-full', collapsed && 'justify-center')}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <ChevronRight size={18} className={clsx('shrink-0 transition-transform', collapsed ? '' : 'rotate-180')} />
            {!collapsed && <span className="text-xs">Collapse</span>}
          </button>
        </div>
      </aside>

      {/* ── Main content area ─────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto">
        {/* Top bar (breadcrumb + user actions) */}
        <div className="sticky top-0 z-10 bg-white/80 backdrop-blur border-b border-navy-100 px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-navy-500">
            <HeartPulse size={14} className="text-teal-600" />
            <span className="font-medium text-navy-700">MedMonitor</span>
            <ChevronRight size={14} />
            <span className="capitalize">{user?.role}</span>
          </div>
          {unread > 0 && user?.role !== 'admin' && (
            <button
              onClick={() => { navigate(`/${user?.role}/dashboard`); clearUnread() }}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs font-semibold hover:bg-red-100 transition-colors animate-pulse-slow"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
              {unread} new alert{unread !== 1 ? 's' : ''}
            </button>
          )}
        </div>

        {/* Page content */}
        <div className="p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
