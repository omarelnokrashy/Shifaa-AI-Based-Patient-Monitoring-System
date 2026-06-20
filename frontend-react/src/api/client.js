/**
 * API client — wraps Axios.
 *
 * When VITE_DATA_MODE=mock, every function returns mock data after a small
 * simulated delay, so the UI is fully exercisable without the backend running.
 *
 * When VITE_DATA_MODE=live, real HTTP calls are made to VITE_API_URL.
 * The token is injected automatically via an Axios request interceptor.
 */
import axios from 'axios'
import useAuthStore from '../store/authStore'
import {
  MOCK_PATIENTS, MOCK_ALERTS, MOCK_USERS,
  MOCK_SERVICE_HEALTH, MOCK_MONITORING_SESSIONS,
} from '../mock/data'

const IS_MOCK = import.meta.env.VITE_DATA_MODE !== 'live'
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// ── Axios instance ────────────────────────────────────────────────────────────
export const http = axios.create({ baseURL: BASE_URL })

// Attach JWT on every request
http.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// On 401, clear auth and redirect to /login
http.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

/**
 * Resolves after a fixed number of milliseconds — used to simulate network
 * latency in mock mode.
 *
 * @param {number} [ms=350] - Milliseconds to wait.
 * @returns {Promise<void>}
 */
const delay = (ms = 350) => new Promise((r) => setTimeout(r, ms))

// ── Auth ─────────────────────────────────────────────────────────────────────
/**
 * Authenticate a user and return a JWT access token.
 *
 * @param {string} email    - The user's email address.
 * @param {string} password - The user's password (min 4 chars in mock mode).
 * @returns {Promise<string>} The JWT access token string.
 * @throws {Error} If credentials are invalid (mock) or the server rejects them.
 */
export const apiLogin = async (email, password) => {
  if (IS_MOCK) {
    await delay()
    const roleMap = {
      'doctor@hospital.com':  { role: 'doctor', name: 'Dr. Ahmed Hassan', id: 1 },
      'nurse@hospital.com':   { role: 'nurse',  name: 'Nurse Sara Mohamed', id: 2 },
      'admin@hospital.com':   { role: 'admin',  name: 'Admin Omar Nour', id: 3 },
    }
    const match = roleMap[email]
    if (!match || password.length < 4) throw new Error('Invalid credentials')
    // Create a fake JWT-like token (not truly signed — only for mock)
    const payload = btoa(JSON.stringify({ sub: String(match.id), role: match.role, name: match.name }))
    return `mock.${payload}.sig`
  }
  const { data } = await http.post('/api/auth/login', { email, password })
  return data.access_token
}

// ── Patients ──────────────────────────────────────────────────────────────────
/**
 * Fetch all patients, optionally filtered by a name search string.
 *
 * @param {string} [search=''] - Case-insensitive substring to filter by patient name.
 * @returns {Promise<Object[]>} Array of patient objects.
 */
export const apiGetPatients = async (search = '') => {
  if (IS_MOCK) {
    await delay()
    const user = useAuthStore.getState().user
    let list = MOCK_PATIENTS
    if (user && user.role === 'doctor') {
      list = list.filter((p) => p.id % 2 !== 0)
    } else if (user && user.role === 'nurse') {
      list = list.filter((p) => p.id % 2 === 0)
    }
    return list.filter((p) =>
      p.name.toLowerCase().includes(search.toLowerCase())
    )
  }
  const { data } = await http.get('/api/patients', { params: { search } })
  return data
}

/**
 * Fetch a single patient by ID.
 *
 * @param {number|string} id - The patient's numeric ID.
 * @returns {Promise<Object|null>} The patient object, or `null` if not found.
 */
export const apiGetPatient = async (id) => {
  if (IS_MOCK) {
    await delay()
    const user = useAuthStore.getState().user
    const patient = MOCK_PATIENTS.find((p) => p.id === Number(id))
    if (!patient) return null
    if (user && user.role === 'doctor' && patient.id % 2 === 0) return null
    if (user && user.role === 'nurse' && patient.id % 2 !== 0) return null
    return patient
  }
  const { data } = await http.get(`/api/patients/${id}`)
  return data
}

/**
 * Create a new patient record.
 *
 * @param {Object} payload - Patient fields (name, dob, gender, etc.).
 * @returns {Promise<Object>} The newly created patient object including generated `id` and `created_at`.
 */
export const apiCreatePatient = async (payload) => {
  if (IS_MOCK) {
    await delay()
    const newP = { ...payload, id: Date.now(), created_at: new Date().toISOString() }
    MOCK_PATIENTS.push(newP)
    return newP
  }
  const { data } = await http.post('/api/patients', payload)
  return data
}

// ── Alerts ────────────────────────────────────────────────────────────────────
/**
 * Fetch alerts, optionally filtered to a single patient.
 *
 * @param {number|string|null} [patientId=null] - Patient ID to filter by, or `null` for all alerts.
 * @returns {Promise<Object[]>} Array of alert objects.
 */
export const apiGetAlerts = async (patientId = null) => {
  if (IS_MOCK) {
    await delay()
    const user = useAuthStore.getState().user
    let list = MOCK_ALERTS
    if (user && user.role === 'doctor') {
      list = list.filter((a) => a.patient_id % 2 !== 0)
    } else if (user && user.role === 'nurse') {
      list = list.filter((a) => a.patient_id % 2 === 0)
    }
    return patientId
      ? list.filter((a) => a.patient_id === Number(patientId))
      : list
  }
  if (patientId) {
    const { data } = await http.get(`/api/patients/${patientId}/alerts`)
    return data
  }
  const { data } = await http.get('/api/dashboard/summary')
  return data.recent_alerts
}

/**
 * Mark an alert as acknowledged by a specific user.
 *
 * @param {number} alertId - The ID of the alert to acknowledge.
 * @param {number|string} userId - The ID of the user acknowledging the alert.
 * @returns {Promise<Object>} Confirmation object (e.g. `{ ok: true }`).
 */
export const apiAcknowledgeAlert = async (alertId, userId) => {
  if (IS_MOCK) {
    await delay(150)
    const a = MOCK_ALERTS.find((x) => x.id === alertId)
    if (a) a.acknowledged = true
    return { ok: true }
  }
  const { data } = await http.patch(`/api/dashboard/alerts/${alertId}/acknowledge`, { acknowledged_by: userId })
  return data
}

// ── Arrhythmia ────────────────────────────────────────────────────────────────
/**
 * Submit an ECG signal for two-stage arrhythmia analysis.
 *
 * @param {number|string} patientId - The patient the signal belongs to.
 * @param {number[]} signal         - Raw ECG sample array.
 * @param {number[]|null} [qrs7]    - Optional 7-beat QRS feature vector for stage-2 sub-classification.
 * @returns {Promise<Object>} Analysis result containing `stage1`, `stage1_confidence`,
 *   `stage2_class`, `stage2_confidence`, `all_probabilities`, `alert_created`, and `alert_id`.
 */
export const apiAnalyzeECG = async (patientId, signal, qrs7 = null) => {
  if (IS_MOCK) {
    await delay(1200) // simulate inference latency
    const isAbnormal = Math.random() > 0.4
    const subtypes = ['AF', 'IAVB', 'SB', 'STach']
    return {
      patient_id: patientId,
      stage1: isAbnormal ? 'Abnormal' : 'Normal',
      stage1_confidence: isAbnormal ? 0.89 + Math.random() * 0.1 : 0.91 + Math.random() * 0.08,
      stage2_class: isAbnormal ? subtypes[Math.floor(Math.random() * subtypes.length)] : null,
      stage2_confidence: isAbnormal ? 0.75 + Math.random() * 0.2 : null,
      all_probabilities: {
        binary: { Normal: isAbnormal ? 0.11 : 0.93, Abnormal: isAbnormal ? 0.89 : 0.07 },
      },
      alert_created: isAbnormal,
      alert_id: isAbnormal ? Math.floor(Math.random() * 9000 + 1000) : null,
      error: null,
    }
  }
  const { data } = await http.post('/api/arrhythmia/analyze', { patient_id: patientId, signal, qrs7 })
  return data
}

// ── Dashboard ──────────────────────────────────────────────────────────────────
/**
 * Fetch the dashboard summary including alert counts, recent alerts, service
 * health, active monitoring sessions, and 24-hour chat usage.
 *
 * @returns {Promise<Object>} Dashboard payload with keys:
 *   `alert_counts`, `recent_alerts`, `service_health`, `active_sessions`, `chat_count_24h`.
 */
export const apiGetDashboard = async () => {
  if (IS_MOCK) {
    await delay()
    const user = useAuthStore.getState().user
    let alerts = MOCK_ALERTS
    let sessions = MOCK_MONITORING_SESSIONS
    if (user && user.role === 'doctor') {
      alerts = alerts.filter((a) => a.patient_id % 2 !== 0)
      sessions = sessions.filter((s) => s.patient_id % 2 !== 0)
    } else if (user && user.role === 'nurse') {
      alerts = alerts.filter((a) => a.patient_id % 2 === 0)
      sessions = sessions.filter((s) => s.patient_id % 2 === 0)
    }
    return {
      alert_counts:    [
        { alert_type: 'arrhythmia', count: alerts.filter(a => a.alert_type === 'arrhythmia').length },
        { alert_type: 'fall',       count: alerts.filter(a => a.alert_type === 'fall').length },
        { alert_type: 'seizure',    count: alerts.filter(a => a.alert_type === 'seizure').length },
      ],
      recent_alerts:   alerts,
      service_health:  MOCK_SERVICE_HEALTH,
      active_sessions: { fall: sessions.filter(s => s.type === 'fall'), seizure: sessions.filter(s => s.type === 'seizure') },
      chat_count_24h:  47,
    }
  }
  const { data } = await http.get('/api/dashboard/summary')
  return data
}

// ── Admin: Users ──────────────────────────────────────────────────────────────
/**
 * Fetch all registered system users (admin only).
 *
 * @returns {Promise<Object[]>} Array of user objects.
 */
export const apiGetUsers = async () => {
  if (IS_MOCK) { await delay(); return MOCK_USERS }
  const { data } = await http.get('/api/admin/users')
  return data
}

/**
 * Create a new system user (admin only).
 *
 * @param {Object} payload - User fields (name, email, password, role, etc.).
 * @returns {Promise<Object>} The newly created user object including generated `id`, `is_active`, and `created_at`.
 */
export const apiCreateUser = async (payload) => {
  if (IS_MOCK) {
    await delay()
    const u = { ...payload, id: Date.now(), is_active: true, created_at: new Date().toISOString() }
    MOCK_USERS.push(u)
    return u
  }
  const { data } = await http.post('/api/admin/users', payload)
  return data
}

/**
 * Deactivate a user account (sets `is_active` to `false`).
 *
 * @param {number|string} id - The user ID to deactivate.
 * @returns {Promise<Object>} The updated user object.
 */
export const apiDeactivateUser = async (id) => {
  if (IS_MOCK) {
    await delay(200)
    const u = MOCK_USERS.find((x) => x.id === id)
    if (u) u.is_active = false
    return u
  }
  const { data } = await http.patch(`/api/admin/users/${id}/deactivate`)
  return data
}

/**
 * Re-activate a previously deactivated user account (sets `is_active` to `true`).
 *
 * @param {number|string} id - The user ID to activate.
 * @returns {Promise<Object>} The updated user object.
 */
export const apiActivateUser = async (id) => {
  if (IS_MOCK) {
    await delay(200)
    const u = MOCK_USERS.find((x) => x.id === id)
    if (u) u.is_active = true
    return u
  }
  const { data } = await http.patch(`/api/admin/users/${id}/activate`)
  return data
}

// ── Monitoring sessions ────────────────────────────────────────────────────────
/**
 * Start a fall-detection monitoring session for a patient in a given room.
 *
 * @param {number|string} patientId - The patient to monitor.
 * @param {string} roomId           - Identifier for the monitoring room/camera.
 * @returns {Promise<Object>} Session info containing `room_id`, `patient_id`, and `ws_url`.
 */
export const apiStartFallMonitoring = async (patientId, roomId) => {
  if (IS_MOCK) { await delay(); return { room_id: roomId, patient_id: patientId, ws_url: null } }
  const { data } = await http.post('/api/monitoring/fall/start', { patient_id: patientId, room_id: roomId })
  return data
}

/**
 * Start a seizure-detection monitoring session for a patient.
 *
 * @param {number|string} patientId    - The patient to monitor.
 * @param {string} source              - Video/sensor source identifier.
 * @param {'monitor'|'analyze'} [mode='monitor'] - Operating mode: continuous monitoring or single-clip analysis.
 * @returns {Promise<Object>} Session info containing `session_id` and `alive` status.
 */
export const apiStartSeizureMonitoring = async (patientId, source, mode = 'monitor') => {
  if (IS_MOCK) { await delay(); return { session_id: String(patientId), alive: true } }
  const { data } = await http.post('/api/monitoring/seizure/start', { patient_id: patientId, source, mode })
  return data
}

/**
 * Trigger random patient assignment to doctors and nurses (admin only).
 *
 * @returns {Promise<Object>} Status message.
 */
export const apiRandomlyAssignPatients = async () => {
  if (IS_MOCK) {
    await delay(500)
    return { status: 'success', message: 'Mock patient assignments created successfully.' }
  }
  const { data } = await http.post('/api/admin/assign-patients')
  return data
}

