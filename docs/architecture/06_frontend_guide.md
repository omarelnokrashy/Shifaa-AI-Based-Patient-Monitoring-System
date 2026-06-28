# 06 — React Frontend Architecture Guide

## 6.1 Overview

The system frontend has been modernized from a single-file legacy interface into a fully modular **React Single Page Application (SPA)** built with **Vite**, **Tailwind CSS**, and **Zustand**. 

The client communicates with the FastAPI backend using REST APIs (via Axios) and persistent WebSockets for live telemetry and real-time alerts. It supports a dual-mode execution strategy (Mock vs. Live) allowing offline demonstration and developer testing out of the box.

*   **Framework**: React 18+ (Functional Components & Hooks)
*   **Build Tool**: Vite (Fast HMR & Rollup bundling)
*   **Styling**: Tailwind CSS (Utility-first CSS) + Custom Clinical Palette
*   **Icons**: Lucide React
*   **Charting**: Recharts (ECG svg visualizer)
*   **State Management**: Zustand (In-memory stores + LocalStorage persistence)
*   **Routing**: React Router DOM v6

---

## 6.2 Directory Structure

The frontend application code is situated entirely within the `frontend-react/` directory, structured as follows:

```
frontend-react/
├── public/
├── src/
│   ├── api/
│   │   └── client.js             # Unified Axios instance, REST wrapper, and mock fallback
│   ├── components/
│   │   ├── chat/
│   │   │   └── ChatPanel.jsx     # Streaming chat interface with thinking collapse
│   │   ├── ecg/
│   │   │   └── ECGChart.jsx      # SVG 12-lead charts and anomaly classifier panels
│   │   ├── layout/
│   │   │   └── NavShell.jsx      # Role-aware navigation sidebar & top telemetry bar
│   │   ├── monitoring/
│   │   │   └── AlertFeed.jsx     # WebSocket synchronized active patient alerts list
│   │   ├── ui/                   # Reusable base clinical design components
│   │   │   ├── Badge.jsx         # Status, severity, and alert category badges
│   │   │   ├── Button.jsx        # Buttons supporting loader states and sizes
│   │   │   ├── Card.jsx          # Flexible clinical dashboard panels
│   │   │   ├── Input.jsx         # Form fields and selection drop-downs
│   │   │   └── Modal.jsx         # Accessible overlays for patient registration
│   │   └── utils/
│   │       └── time.js           # Time formatting and DOB age calculators
│   ├── hooks/
│   │   ├── useAlertsWS.js        # Maintains telemetry WS connection & store inserts
│   │   └── useChatStream.js      # Handles chat WS message streaming parser loops
│   ├── mock/
│   │   └── data.js               # Mock patients, lab results, telemetry, and alerts
│   ├── pages/
│   │   ├── admin/
│   │   │   ├── AdminDashboard.jsx    # Microservices health telemetry grid
│   │   │   └── UserManagementPage.jsx# Hospital user account activation panels
│   │   ├── auth/
│   │   │   └── LoginPage.jsx     # Clean light-themed login + demo credentials loader
│   │   ├── doctor/
│   │   │   ├── DoctorDashboard.jsx   # Clinical feed dashboard
│   │   │   ├── LiveMonitoringPage.jsx# Telemetry grid for fall & seizure cams
│   │   │   ├── PatientDetailPage.jsx # Tabbed client file (Overview, Chat, ECG, logs)
│   │   │   └── PatientListPage.jsx   # Searchable register of patients
│   │   └── nurse/
│   │       └── NurseDashboard.jsx    # Triage dashboard focused on unacknowledged feeds
│   ├── store/
│   │   ├── alertsStore.js        # Global telemetry alerts array
│   │   └── authStore.js          # JWT storage, decode, and user session details
│   ├── App.jsx                   # Central routing registry and Role-based guards
│   ├── index.css                 # Typography injection, theme classes, and scroll behaviors
│   └── main.jsx                  # Virtual DOM root mounter
├── index.html                    # Mounter markup and Google Fonts imports
├── tailwind.config.js            # Custom color palette and typography declarations
└── package.json                  # Dependencies registry
```

---

## 6.3 Routing & Role-Based Access Control (RBAC)

Routing is managed declaratively inside `App.jsx` using `react-router-dom`. The application protects clinical views from unauthorized users by implementing a custom **`RoleGuard`** component.

```
                  / (Root Redirect)
                         │
         ┌───────────────┴───────────────┐
   User Present?                   User Absent?
         │                               │
  Redirect to Role                     Redirect
  Dashboard Route                    to /login
  (/doctor/*, /nurse/*, /admin/*)
```

### Route Guard Configuration
The `RoleGuard` extracts user information directly from the Zustand `authStore` session. If a user tries to access a path that doesn't correspond to their role (e.g. a Nurse navigating to an Admin page), they are redirected automatically to their respective role's dashboard.

```jsx
function RoleGuard({ allowedRole }) {
  const user = useAuthStore((s) => s.user)
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== allowedRole) {
    const homes = {
      doctor: '/doctor/dashboard',
      nurse: '/nurse/dashboard',
      admin: '/admin/dashboard'
    }
    return <Navigate to={homes[user.role] || '/login'} replace />
  }
  return <Outlet />
}
```

---

## 6.4 State Management Systems

Global state is split into two lightweight, single-responsibility **Zustand** stores.

### 6.4.1 Auth Store (`authStore.js`)
Manages JWT storage, automated decoding using `jwt-decode`, and session lifecycle.
*   **JWT Storage**: Persisted directly to `localStorage` with key `med-auth`.
*   **Automatic Decoding**: Extracts `sub` (user ID), `name`, and `role` to populate the `user` state.
*   **Store Interface**:
    ```javascript
    const useAuthStore = create(persist((set) => ({
      token: null,
      user: null, // { id, name, role }
      login: (token) => {
        const payload = jwtDecode(token);
        set({ token, user: { id: payload.sub, name: payload.name, role: payload.role } });
      },
      logout: () => set({ token: null, user: null })
    })))
    ```

### 6.4.2 Alerts Store (`alertsStore.js`)
Stores real-time telemetry events arriving over the active WebSocket channel during a clinician's shift.
*   **Session Lifecycle**: Stored in-memory to survive page refreshes, capped at the most recent 200 events.
*   **State**: `alerts` (array), `unread` (counter).
*   **Actions**: `addAlert(alert)`, `acknowledge(id)`, `clearUnread()`, `reset()`.

---

## 6.5 WebSocket Telemetry Hooks

Real-time capabilities are driven by dedicated hooks that handle WebSocket lifecycles and backend message frames.

### 6.5.1 Alert Telemetry Hook (`useAlertsWS.js`)
Maintains a persistent connection to `ws://localhost:8000/api/ws/alerts` using the clinician's JWT.
*   **Auto-Reconnect**: Implements exponential back-off up to a maximum delay of 30 seconds.
*   **Data Injection**: In `mock` mode, it launches a `setInterval` timer to inject realistic synthetic alerts into the global `alertsStore` every 25 seconds for user evaluation.

```
[WebSocket Frame Received] ──► Parse JSON ──► Check Type 'alert' ──► Dispatch `addAlert()`
```

### 6.5.2 AI Chat Streaming Hook (`useChatStream.js`)
Manages the connection state for streaming conversational agents and reasoning output.
*   **Thinking Block Parser**: Listens for the backend `<think>` tags via `think_start`, `think` (chunks), and `think_done` frames. It handles live population of reasoning steps separately from the final answer.
*   **Mock Stream Simulation**: In `mock` mode, it divides text arrays into small character chunks to simulate network streaming, feeding them back to the chat component on a 25ms timer.
*   **Server-Sent Events (SSE) Image Streaming**: For image uploads, it opens a POST connection using `/api/chat/analyze-image` and processes the streamed tokens using an SSE event parser, supporting real-time rendering of thinking and visual analysis steps.

### 6.5.3 Image Upload and Preview Panel
The chat input bar supports attaching medical scans:
*   **File Attachment Handler**: Integrates a hidden file input triggered by a paperclip/image icon.
*   **Thumbnail Preview Box**: Displays a preview image and file details directly above the text box prior to submission, with a button to remove the selection.
*   **Scan Type Selector**: An inline dropdown to select the type of scan (e.g. Chest X-Ray, CT/MRI, Lab Report) to feed domain-specific templates to the LLM.
*   **Inline Bubble Rendering**: Once sent, the uploaded image is rendered inside the user bubble within the chat transcript.

---

## 6.6 Clinical Components Library (`components/ui`)

A premium design language was implemented through reusable Clinical UI components built with Tailwind CSS:

*   **`Button`**: Supports variants (`primary`, `secondary`, `danger`, `ghost`), sizes (`sm`, `md`, `lg`), and inline spin loaders with disabled states to prevent double submission during API calls.
*   **`Card`**: Structured dashboard blocks containing header titles, optional action components, and layout padding parameters.
*   **`Modal`**: Keyboard-accessible dialog overlays with backdrop clicks, title bars, and footer actions used for patient registration.
*   **`Input` / `Select`**: Forms with standard layouts, custom label formatting, validation states, inline hints, and error alerts.
*   **`Badge`**: Color-coded categorization pills including:
    *   `SeverityBadge`: Combines colored borders, background gradients, high-visibility text, and Lucide icons (e.g. Critical, High, Medium, Low) to guarantee usability without relying on color alone.
    *   `StatusBadge`: Displays health metrics (e.g., Online, Degraded, Offline).

---

## 6.7 Interactive Clinical Visualizations

### 6.7.1 ECG Chart Viewer (`ECGChart.jsx`)
An SVG-based graphing component built using **Recharts** to visualize multi-lead clinical electrocardiograms.
*   **Interactive Controls**: Toggle switches allow clinicians to view individual leads (Lead I, Lead II, Lead V1, Lead V5) or display all leads aligned in a vertical grid.
*   **Inference Dashboard**: Displays results from the backend Arrhythmia detection service:
    *   **Stage 1**: Binary rhythm classification (Normal / Abnormal) with AI confidence score.
    *   **Stage 2**: Specific class mapping (AF, IAVB, SB, STach) with a confidence indicator bar.
    *   **All Probabilities**: Renders a comparative bar chart displaying all class probabilities.

### 6.7.2 Live Monitoring Grid (`LiveMonitoringPage.jsx`)
Represents camera feeds from patient rooms (for fall and seizure detection) as interactive cards.
*   **Status Codes**: Visualized as `NORMAL` (Green), `INITIALISING` (Amber), or `ALERT ACTIVE` (Red).
*   **Seizure Countdown Latch**: Tracks the backend's 30-second post-event latch window. During a latch condition, it displays a countdown progress bar that depletes from 100% to 0% in real-time, holding the alert card in an active flashing state until the window expires.

---

## 6.8 Dual-Mode Execution Strategy

The React frontend switches seamlessly between standalone mock demonstrations and production backend API execution via a single environment variable:

*   **`VITE_DATA_MODE`**: Configuration flag in `.env`.
    *   `mock`: Uses simulated delays, in-memory modifications to lists, local WS timer triggers, and mock endpoints inside `api/client.js`.
    *   `live`: Uses HTTP communication to the `VITE_API_URL` endpoint and initiates real WebSocket streams to `VITE_WS_URL`.

---

## 6.9 Color Palette & Theme Tokens

Tailwind colors are mapped to clinical roles and urgency definitions:

| Theme Key | Visual Palette | Intended Use Case |
|---|---|---|
| **Navy-900 / 950** | Deep Dark Blue | Sidebars, primary panels, dark background containers. |
| **Teal-600 / 700** | Professional Medical Teal | Active states, branding headers, primary buttons. |
| **Red-600 / 50** | Crimson / Light Pink | Critical alerts, fall notifications, seizure alarms. |
| **Orange-600 / 50** | Amber / Light Orange | High-severity alerts, abnormal heart rhythms. |
| **Yellow-600 / 50** | Gold / Light Yellow | Medium-severity events, service warning states. |
| **Green-600 / 50** | Emerald / Light Green | Normal vitals, system checks, resolved states. |

---

*Next: [Setup & Deployment Guide →](07_setup_guide.md)*
