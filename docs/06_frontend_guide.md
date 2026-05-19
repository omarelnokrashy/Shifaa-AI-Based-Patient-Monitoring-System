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
│  (340px wide)  │                                             │
│                │  ┌─────────────────────────────────────┐    │
│  👥 Patient Hub│  │ CHAT HEADER                         │    │
│  [+ Add]       │  │ Mode Switch (Patient / General)     │    │
│                │  │ patient info pill                   │    │
│  [Tabs]        │  └─────────────────────────────────────┘    │
│  Recent|Browse │                                             │
│  |Search       │  ┌─────────────────────────────────────┐    │
│                │  │ MESSAGES AREA (scrollable)          │    │
│  [Tab Content] │  │ Bot messages (left-aligned)         │    │
│  (List or Cards│  │ 🧠 Thinking... (Expandable)         │    │
│   w/ filters)  │  │ Doctor messages (right-aligned)     │    │
│                │  │ Image previews for uploads          │    │
│                │  └─────────────────────────────────────┘    │
│                │                                             │
│  [Sign Out]    │  ┌─────────────────────────────────────┐    │
│                │  │ INPUT AREA                          │    │
│                │  │ [📎] [Textarea]      [Send / Stop]  │    │
│                │  └─────────────────────────────────────┘    │
└────────────────┴─────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  IMAGE UPLOAD MODAL (z-index: 200, hidden by default)        │
│  📎 Analyze Medical Image form                               │ 
│  - Image Type (X-Ray, CT, Lab Report, etc.)                  │
│  - File Input                                                │
│  - Specific Question (Optional)                              │
│  - Cancel | Analyze buttons (Triggers SSE Stream)            │
└──────────────────────────────────────────────────────────────┘

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
| `switchTab(tabId)` | Switches between Recent, Browse, and Search tabs |
| `loadBrowse(reset)` | Fetches paginated patient grid with active filters |
| `applyFilter(el)` | Applies Gender/Blood Type filters and re-fetches grid |
| `searchPatients(val)` | Live search for the Search tab |
| `trackRecent(p)` | Saves selected patient to localStorage 'recentPts' (max 8) |
| `selectPatient(p)` | Marks patient active, clears chat, opens WebSocket |
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
let currentMode = 'patient';                // 'patient' or 'general'
let botMsgDiv = null;                       // DOM element for streaming bot message
let thinkBlock = null;                      // DOM element for <think> stream
```

---

## 6.5 WebSocket Message Handling

```
```
WebSocket CONNECT on patient select or general mode
    │
    ├── Send: { query, patient_id, mode, token }
    │
    ├── Receive: { type: "think_start" } → build think UI block
    │
    ├── Receive: { type: "think", chunk: "..." } → append to thinkBlock
    │
    ├── Receive: { type: "think_done", duration: 2.1 } → finalize think UI
    │
    ├── Receive: { type: "chunk", chunk: "...", done: false } → append to markdown body
    │
    └── Receive: { type: "done", done: true } → Re-enable Send button
```

Note: Multi-modal image analysis (`POST /api/chat/analyze-image`) uses **Server-Sent Events (SSE)** instead of WebSockets, but returns the exact same JSON event sequence, allowing the frontend to use a unified parsing loop `handleStreamEvent(data)`.

---

## 6.6 Advanced UI & User Experience Features

The frontend interface incorporates two custom, high-end visual and interaction patterns:

### A. Collapsible Reasoning & Thought Blocks (`.think-block`)
When the model starts its step-by-step reasoning process, the frontend dynamically constructs an expandable container inside the bot's message bubble.
- **Visual Design**: The container has a modern, clean HSL-tailored neutral slate background (`#f8fafc`), an e2e8f0 border, and a distinct medical-teal accent bar on the left (`border-left: 4px solid #0d7377`) indicating clinical reflection.
- **Dynamic Real-Time Expand**: While the model is actively thinking, the box remains fully expanded and renders the markdown thoughts line-by-line using `marked.js` as they stream.
- **Auto-Collapse**: Once thinking is complete (the `think_done` event is received), the interface updates the header with the duration (e.g. `🧠 Thought for 3.4s`) and **automatically collapses the box** to draw the doctor's immediate focus to the final clinical answer.
- **Interactive Chevron**: Users can click the header to toggle the reasoning block open or closed at any time. The arrow (`▼`) rotates smoothly (`180deg`) using Vanilla CSS transitions.

### B. Intelligent Mode Reset (`setMode`)
When transitioning between Patient QA and General Q&A modes, the interface performs automatic context switching:
- **Chat Reset**: Toggling to **General Q&A** automatically wipes the chat history (`msgs.innerHTML = ''`) to prevent confusion between general clinical QA and specific patient data.
- **Welcome Broadcast**: It instantly triggers an introductory bot message explaining what the model can do in general medical mode, allowing for a completely fresh chat experience (serving as a quick "New Chat" button).

---

## 6.7 Markdown Rendering

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
