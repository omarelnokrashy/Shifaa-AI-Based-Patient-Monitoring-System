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

const delay = (ms = 350) => new Promise((r) => setTimeout(r, ms))

// ── Auth ─────────────────────────────────────────────────────────────────────
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
export const apiGetPatients = async (search = '') => {
  if (IS_MOCK) {
    await delay()
    return MOCK_PATIENTS.filter((p) =>
      p.name.toLowerCase().includes(search.toLowerCase())
    )
  }
  const { data } = await http.get('/api/patients', { params: { search } })
  return data
}

export const apiGetPatient = async (id) => {
  if (IS_MOCK) {
    await delay()
    return MOCK_PATIENTS.find((p) => p.id === Number(id)) || null
  }
  const { data } = await http.get(`/api/patients/${id}`)
  return data
}

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
export const apiGetAlerts = async (patientId = null) => {
  if (IS_MOCK) {
    await delay()
    return patientId
      ? MOCK_ALERTS.filter((a) => a.patient_id === Number(patientId))
      : MOCK_ALERTS
  }
  const { data } = await http.get('/api/dashboard/summary')
  return data.recent_alerts
}

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
export const apiGetDashboard = async () => {
  if (IS_MOCK) {
    await delay()
    return {
      alert_counts:    [
        { alert_type: 'arrhythmia', count: 3 },
        { alert_type: 'fall',       count: 1 },
        { alert_type: 'seizure',    count: 2 },
      ],
      recent_alerts:   MOCK_ALERTS,
      service_health:  MOCK_SERVICE_HEALTH,
      active_sessions: { fall: MOCK_MONITORING_SESSIONS.filter(s => s.type === 'fall'), seizure: MOCK_MONITORING_SESSIONS.filter(s => s.type === 'seizure') },
      chat_count_24h:  47,
    }
  }
  const { data } = await http.get('/api/dashboard/summary')
  return data
}

// ── Admin: Users ──────────────────────────────────────────────────────────────
export const apiGetUsers = async () => {
  if (IS_MOCK) { await delay(); return MOCK_USERS }
  const { data } = await http.get('/api/admin/users')
  return data
}

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
export const apiStartFallMonitoring = async (patientId, roomId) => {
  if (IS_MOCK) { await delay(); return { room_id: roomId, patient_id: patientId, ws_url: null } }
  const { data } = await http.post('/api/monitoring/fall/start', { patient_id: patientId, room_id: roomId })
  return data
}

export const apiStartSeizureMonitoring = async (patientId, source, mode = 'monitor') => {
  if (IS_MOCK) { await delay(); return { session_id: String(patientId), alive: true } }
  const { data } = await http.post('/api/monitoring/seizure/start', { patient_id: patientId, source, mode })
  return data
}
