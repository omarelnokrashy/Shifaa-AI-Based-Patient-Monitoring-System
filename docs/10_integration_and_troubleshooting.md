# 10 — Integration & Troubleshooting Log

This document serves as an academic and developer reference for the integration, diagnostics, and style adjustments made during the transition from the legacy single-file HTML prototype to the unified React SPA.

---

## 10.1 Frontend Rebuild Summary

The frontend was refactored into a modern, production-ready React Single Page Application (SPA).

1.  **Framework Setup**: Reconfigured the UI structure around React 18 and Vite.
2.  **Role-Based Security**: Implemented a client-side `RoleGuard` wrapper that reads session credentials decoded from the JWT token and dynamically gates access for the Doctor, Nurse, and Admin interfaces.
3.  **Unified Data Layer**: Standardized communications under `api/client.js` supporting a toggleable `VITE_DATA_MODE` (`mock` vs. `live`), facilitating easy development and standalone verification.

---

## 10.2 Conda-Isolated Node.js Environment

To avoid global package mutations and administrative (`sudo`) requirements, Node.js and the Node Package Manager (`npm`) were installed directly inside the project's custom Conda environment:

```bash
# Activate the existing project environment
conda activate medical_chatbot

# Install Node.js and npm via the conda-forge channel
conda install -c conda-forge nodejs -y

# Verify localized paths
which node  # Outputs: /home/omar/anaconda3/envs/medical_chatbot/bin/node
which npm   # Outputs: /home/omar/anaconda3/envs/medical_chatbot/bin/npm
```

This ensures that the React compilation pipeline, HMR dev server, and package installations remain entirely self-contained.

---

## 10.3 Troubleshooting & Debugging Logs

### 10.3.1 Case 1: White Screen Runtime Crash (Lucide-React Export Issue)

#### Symptom:
After starting the dev server and loading the homepage (`http://localhost:5173`), the browser displayed a completely white screen. The compiler succeeded without errors, but the browser could not execute the bundle.

#### Diagnosis Method:
Because default browser automated tools were limited by sandbox configurations, a headless instance of **Brave Browser** was launched with remote debugging enabled to intercept runtime exceptions:

```bash
# Launch headless Brave targeting the local Vite port
/usr/bin/brave-browser --headless --remote-debugging-port=9222 http://localhost:5173

# Query the DevTools WebSocket descriptor
curl -s http://localhost:9222/json
```

A custom Node.js debugger script was connected to the DevTools WebSocket endpoint to capture console events:

```
[RUNTIME EXCEPTION]: {
  "text": "Uncaught",
  "lineNumber": 8,
  "url": "http://localhost:5173/src/pages/doctor/PatientListPage.jsx",
  "exception": {
    "className": "SyntaxError",
    "description": "SyntaxError: The requested module '/node_modules/.vite/deps/lucide-react.js' does not provide an export named 'Flask'"
  }
}
```

#### Cause:
In `PatientListPage.jsx`, the import statement contained `Flask` and `Pill` icons:
```javascript
import { Search, Plus, AlertCircle, Pill, Flask } from 'lucide-react'
```
However, the version of `lucide-react` installed did not export `Flask` (it was renamed or deprecated in newer releases). Since this script was evaluated at load time, the browser aborted execution immediately, rendering a blank screen.

#### Resolution:
Since `Search`, `Pill`, and `Flask` were legacy imports that were no longer utilized within `PatientListPage.jsx`, they were removed from the file, simplifying the import statement to:
```javascript
import { Plus, AlertCircle } from 'lucide-react'
```

---

### 10.3.2 Case 2: Invisible Input Text on Login Card (Contrast Styling Issue)

#### Symptom:
On the login screen (`/login`), typing credentials into the Email and Password fields resulted in invisible/white text.

#### Cause:
The `<Input>` component in `components/ui/Input.jsx` was hardcoded to use light-theme utilities:
```javascript
className={clsx('bg-white text-navy-900', className)}
```
However, `LoginPage.jsx` passed custom dark-theme class overrides to match the dark login card:
```javascript
className="bg-navy-800 text-white"
```
Because of Tailwind CSS class precedence rules in the compiled stylesheet, the browser evaluated the CSS classes in a conflicting order: the white background (`bg-white`) took precedence, and the white text (`text-white`) also took precedence. This resulted in white text inside a white box.

#### Resolution:
The login card was updated to use a clean light theme, matching the dashboard's design system:
- Updated Card wrapper: `bg-white rounded-2xl p-8 border border-navy-200 shadow-xl`
- Updated title/subtitle text elements: `text-navy-900` / `text-navy-500`
- Removed conflicting dark overrides from `<Input>` calls, letting them render with their default, highly legible white background (`bg-white`) and dark navy text (`text-navy-900`).
- Re-styled demo credential trigger buttons:
  ```javascript
  className="w-full text-left px-3 py-2 rounded-lg bg-navy-50 hover:bg-navy-100 border border-navy-100 hover:border-teal-600/30"
  ```

This layout change fixed contrast accessibility and created a professional appearance that integrates with the main clinical dashboards.
