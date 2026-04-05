# 06 — Frontend Guide

## 6.1 Overview

The frontend is a **single self-contained HTML file** (`frontend/index.html`) with no build steps, no frameworks, and no external JavaScript dependencies except `marked.js` (for Markdown rendering, loaded via CDN).

**File:** `frontend/index.html` (718 lines)  
**Technology:** Vanilla HTML5 + CSS3 + JavaScript (ES2021)  
**External library:** `marked.min.js` (Markdown → HTML rendering)

---

## 6.2 UI Structure

The interface has four main sections:

```
┌──────────────────────────────────────────────────────────────┐
│  LOGIN SCREEN (overlay, z-index: 100)                        │
│  - Email + Password fields                                   │
│  - Sign In button → calls POST /api/auth/login               │
└──────────────────────────────────────────────────────────────┘

┌────────────────┬─────────────────────────────────────────────┐
│  SIDEBAR       │  MAIN AREA                                  │
│  (280px wide)  │                                             │
│                │  ┌─────────────────────────────────────┐    │
│  👥 Patients   │  │ CHAT HEADER                         │    │
│  [+ Add]       │  │ patient name | intent badge         │    │
│                │  └─────────────────────────────────────┘    │
│  [Search box]  │                                             │
│                │  ┌─────────────────────────────────────┐    │
│  Patient list  │  │ MESSAGES AREA (scrollable)          │    │
│  (scrollable)  │  │ Bot messages (left-aligned)         │    │
│                │  │ Doctor messages (right-aligned)     │    │
│                │  │ Typing indicator (animated dots)    │    │
│  [Sign Out]    │  └─────────────────────────────────────┘    │
│                │                                             │
│                │  ┌─────────────────────────────────────┐    │
│                │  │ INPUT AREA                          │    │
│                │  │ [Textarea] [Send ➤ button]          │    │
│                │  └─────────────────────────────────────┘    │
└────────────────┴─────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  MODAL OVERLAY (z-index: 200, hidden by default)             │
│  🆕 Register New Patient form                                │ 
│  - Name, DOB, Gender, Blood Type, Phone                      │
│  - Cancel | Register buttons                                 │
└──────────────────────────────────────────────────────────────┘
```

---

## 6.3 JavaScript Functions

### Authentication

| Function | Description |
|----------|-------------|
| `login()` | Reads email+password, calls `POST /api/auth/login`, stores JWT in `localStorage` |
| `logout()` | Clears `localStorage.token`, reloads page |

### Patient Management

| Function | Description |
|----------|-------------|
| `loadPatients(search)` | Fetches patient list with optional search, renders to sidebar |
| `searchPatients(val)` | Debounced (300ms) call to `loadPatients()` |
| `selectPatient(id, name, meta)` | Marks patient active, clears chat, opens WebSocket |
| `openModal()` | Shows registration modal |
| `closeModal()` | Hides registration modal |
| `registerPatient()` | Submits new patient form to `POST /api/patients` |

### Chat / WebSocket

| Function | Description |
|----------|-------------|
| `connectWebSocket()` | Opens `ws://hostname:8000/api/ws/chat` |
| `sendMessage()` | Sends JSON `{query, patient_id, token}` over WebSocket |
| `handleKey(e)` | Enter key shortcut (without Shift) triggers `sendMessage()` |

### Message Rendering

| Function | Description |
|----------|-------------|
| `addMessage(role, text, intent, sources)` | Creates a message bubble (bot or doctor role) |
| `createBotBubble()` | Creates an empty bot bubble for streaming population |
| `addTypingIndicator()` | Shows animated 3-dot typing indicator |
| `removeTypingIndicator()` | Removes typing indicator |
| `scrollToBottom()` | Auto-scrolls message area to latest message |

---

## 6.4 State Management

The application uses simple global JavaScript variables:

```javascript
let token = localStorage.getItem('token');  // JWT, persisted across sessions
let currentPatient = null;                  // { id, name } of selected patient
let ws = null;                              // Active WebSocket connection
let botMsgDiv = null;                       // DOM element for streaming bot message
let botText = '';                           // Accumulated streaming text
```

---

## 6.5 WebSocket Message Handling

```
WebSocket CONNECT on patient select
    │
    ├── Send: { query, patient_id, token }
    │
    ├── Receive: { chunk: "...", done: false }  →  append chunk to botMsgDiv
    │   (multiple times, re-renders markdown each time)
    │
    └── Receive: { chunk: "", done: true, intent: "...", sources: [...] }
        → Update intent badge in header
        → Render sources at bottom of bot message
        → Re-enable Send button
```

---

## 6.6 Markdown Rendering

Bot responses are rendered as Markdown using `marked.js`. This supports:

- **Bold** and *italic* text
- Bullet and numbered lists
- `code` inline formatting
- Paragraph breaks

The LLM is prompted to use bullet points, which renders cleanly in the chat bubble.

---

## 6.7 Color Palette

| Element | Color | Hex |
|---------|-------|-----|
| Sidebar background | Deep navy | `#1a3a5c` |
| Active patient / Send button hover | Teal | `#0d7377` |
| Doctor's chat bubble | Deep navy | `#1a3a5c` |
| Bot's chat bubble | White | `#ffffff` |
| Body background | Light blue-gray | `#f0f4f8` |
| Intent badge accent | Teal | `#0d7377` |
| Link/accent text | Light blue | `#aac8e0` |

---

## 6.8 API URL Detection

The frontend automatically selects the correct backend URL:

```javascript
const API = (window.location.protocol === 'file:'
    ? 'http://localhost'
    : (window.location.protocol + '//' + window.location.hostname)
) + ':8000';
```

This means the file works when:

- Opened directly as a file (`file:///...`) → uses `http://localhost:8000`
- Served from a web server on the same host → uses the current hostname

---

*Next: [Setup Guide →](07_setup_guide.md)*
