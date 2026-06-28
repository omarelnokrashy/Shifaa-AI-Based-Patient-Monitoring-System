/**
 * main.jsx — React application entry point.
 *
 * Bootstraps the app by:
 *  1. Wrapping the root `<App />` in `<React.StrictMode>` for development checks.
 *  2. Providing `<BrowserRouter>` so React Router has a history context.
 *  3. Mounting the resulting tree into the `#root` DOM element defined in index.html.
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)
