# Frontend React — Medical Monitoring System

## Quick Start

```bash
# 1. Install dependencies (requires Node 18+)
cd frontend-react
npm install

# 2. Configure environment
cp .env.example .env
# Edit .env — set VITE_DATA_MODE=mock for demo without backend

# 3. Run dev server
npm run dev
# → http://localhost:5173
```

## Demo Login (mock mode)

| Role   | Email                   | Password   | Redirects to         |
|--------|-------------------------|------------|----------------------|
| Doctor | doctor@hospital.com     | doctor123  | /doctor/dashboard    |
| Nurse  | nurse@hospital.com      | nurse123   | /nurse/dashboard     |
| Admin  | admin@hospital.com      | admin123   | /admin/dashboard     |

Click any credential button on the login page to auto-fill.

## Connecting to the live backend

1. Start the FastAPI backend:
   ```bash
   ./start_all_services.sh
   ```
2. Set in `.env`:
   ```
   VITE_API_URL=http://localhost:8000
   VITE_WS_URL=ws://localhost:8000
   VITE_DATA_MODE=live
   ```
3. Restart `npm run dev`.

That's it — the API client automatically switches from mock data to live calls.

## Project Structure

```
src/
├── api/
│   └── client.js          # Axios client + mock/live toggle for all API calls
├── components/
│   ├── ui/                # Button, Card, Badge, Modal, Input — design system
│   ├── layout/            # NavShell (sidebar + topbar, role-aware navigation)
│   ├── chat/              # ChatPanel — streaming, thinking block, markdown
│   ├── monitoring/        # AlertFeed — live alert list with severity indicators
│   ├── ecg/               # ECGChart — Recharts 12-lead display + ArrhythmiaResultCard
│   └── utils/             # time.js — shared formatters
├── hooks/
│   ├── useChatStream.js   # WebSocket chat streaming (mock + live)
│   └── useAlertsWS.js     # Persistent alert WebSocket with reconnect
├── mock/
│   └── data.js            # Realistic mock patients, alerts, users, ECG data
├── pages/
│   ├── auth/              # LoginPage
│   ├── doctor/            # DoctorDashboard, PatientListPage, PatientDetailPage,
│   │                      #   LiveMonitoringPage
│   ├── nurse/             # NurseDashboard (reuses doctor's patient pages)
│   └── admin/             # AdminDashboard, UserManagementPage
├── store/
│   ├── authStore.js       # Zustand: token + decoded user (role, name, id)
│   └── alertsStore.js     # Zustand: live alert list + unread count
├── App.jsx                # Root router with RoleGuard + role-aware redirects
└── main.jsx               # React entry point
```

## Design decisions

### JWT in localStorage vs httpOnly cookies
This prototype stores the JWT in localStorage for simplicity. In a production
hospital deployment, use httpOnly cookies via a `/api/auth/cookie` endpoint
to prevent XSS token theft. The tradeoff: httpOnly cookies require same-origin
or CORS-credentialed requests and a server-side logout. The switch is a
one-component change in `authStore.js` and `api/client.js`.

### Mock / Live toggle
`VITE_DATA_MODE=mock` makes every API function return local data after a
simulated delay, so the entire UI is exercisable without the backend running.
`VITE_DATA_MODE=live` makes real HTTP + WebSocket calls. The toggle is a
single env var — no code changes needed.

### Role-based routing
`RoleGuard` in `App.jsx` checks `user.role` from Zustand. If a doctor tries
to navigate to `/admin/users`, they are redirected to their own dashboard.
The NavShell filters navigation items by role — no separate app builds.

### Alert accessibility
Severity is communicated with **color + icon + label**, never color alone.
`SeverityBadge` always renders the Lucide icon alongside the text label.
Alert rows use a left border color paired with the badge.
