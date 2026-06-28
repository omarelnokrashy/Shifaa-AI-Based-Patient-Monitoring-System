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
 * Fetch chat history for a doctor-patient conversation.
 *
 * @param {number|string} patientId - The patient's ID.
 * @returns {Promise<Object[]>} List of historical chat logs.
 */
export const apiGetChatHistory = async (patientId) => {
  if (IS_MOCK) {
    await delay()
    return []
  }
  const { data } = await http.get(`/api/chat/history/${patientId}`)
  return data
}

/**
 * Fetch general chat history for the logged-in doctor.
 *
 * @returns {Promise<Object[]>} List of historical chat logs.
 */
export const apiGetGeneralChatHistory = async () => {
  if (IS_MOCK) {
    await delay()
    return []
  }
  const { data } = await http.get('/api/chat/general/history')
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
export const apiGetAlerts = async (patientId = null, historyOnly = false) => {
  if (IS_MOCK) {
    await delay()
    const user = useAuthStore.getState().user
    let list = MOCK_ALERTS
    if (user && user.role === 'doctor') {
      list = list.filter((a) => a.patient_id % 2 !== 0)
    } else if (user && user.role === 'nurse') {
      list = list.filter((a) => a.patient_id % 2 === 0)
    }
    if (patientId) {
      let filtered = list.filter((a) => a.patient_id === Number(patientId))
      if (historyOnly) {
        filtered = filtered.filter((a) => a.acknowledged)
      }
      return filtered
    }
    return list
  }
  if (patientId) {
    const { data } = await http.get(`/api/patients/${patientId}/alerts`, {
      params: { history_only: historyOnly }
    })
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

/**
 * Cancel an active alert entirely (no history saved).
 *
 * @param {number} alertId - The ID of the alert to cancel.
 * @returns {Promise<Object>} Confirmation object (e.g. `{ ok: true }`).
 */
export const apiCancelAlert = async (alertId) => {
  if (IS_MOCK) {
    await delay(150)
    const idx = MOCK_ALERTS.findIndex((x) => x.id === alertId)
    if (idx !== -1) MOCK_ALERTS.splice(idx, 1)
    return { ok: true }
  }
  const { data } = await http.delete(`/api/dashboard/alerts/${alertId}/cancel`)
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


// ── Room Management Mock Data & APIs ─────────────────────────────────────────

let MOCK_ROOMS = [
  {
    id: 1,
    room_number: "101",
    room_name: "ICU Bed A",
    floor: "1",
    patient_id: 1,
    monitoring_status: "Monitoring",
    patient: { id: 1, name: "Ahmed Hassan", gender: "Male", dob: "1980-05-15", blood_type: "A+" },
    services: ["ecg", "seizure"],
    nurses: [{ id: 2, name: "Nurse Sara Mohamed", email: "nurse@hospital.com", role: "nurse" }],
    active_alerts: [],
    risk_score: 0.0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  },
  {
    id: 2,
    room_number: "102",
    room_name: "ICU Bed B",
    floor: "1",
    patient_id: 2,
    monitoring_status: "Warning",
    patient: { id: 2, name: "Jane Smith", gender: "Female", dob: "1992-08-22", blood_type: "O-" },
    services: ["fall"],
    nurses: [{ id: 2, name: "Nurse Sara Mohamed", email: "nurse@hospital.com", role: "nurse" }],
    active_alerts: [{ id: 101, alert_type: "fall", severity: "medium", details: { message: "Patient moving near bed edge" }, created_at: new Date().toISOString() }],
    risk_score: 0.65,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  },
  {
    id: 3,
    room_number: "103",
    room_name: "Ward Room A",
    floor: "1",
    patient_id: null,
    monitoring_status: "Idle",
    patient: null,
    services: ["ecg"],
    nurses: [],
    active_alerts: [],
    risk_score: 0.0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  },
  {
    id: 4,
    room_number: "201",
    room_name: "Neurology Suite",
    floor: "2",
    patient_id: 3,
    monitoring_status: "Critical Alert",
    patient: { id: 3, name: "Michael Vance", gender: "Male", dob: "1965-11-02", blood_type: "B+" },
    services: ["ecg", "seizure", "fall"],
    nurses: [{ id: 2, name: "Nurse Sara Mohamed", email: "nurse@hospital.com", role: "nurse" }],
    active_alerts: [{ id: 102, alert_type: "seizure", severity: "critical", details: { gate_score: 0.98 }, created_at: new Date().toISOString() }],
    risk_score: 0.98,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  }
];

export const apiGetRooms = async (params = {}) => {
  if (IS_MOCK) {
    await delay();
    let list = [...MOCK_ROOMS];
    const user = useAuthStore.getState().user;
    if (user && user.role === 'nurse') {
      list = list.filter(r => r.nurses.some(n => n.id === Number(user.id)));
    }
    if (params.search) {
      const s = params.search.toLowerCase();
      list = list.filter(r => 
        r.room_number.includes(s) ||
        (r.room_name && r.room_name.toLowerCase().includes(s)) ||
        (r.patient && r.patient.name.toLowerCase().includes(s)) ||
        r.nurses.some(n => n.name.toLowerCase().includes(s))
      );
    }
    if (params.service) {
      list = list.filter(r => r.services.includes(params.service.toLowerCase()));
    }
    if (params.nurse_id) {
      list = list.filter(r => r.nurses.some(n => n.id === Number(params.nurse_id)));
    }
    if (params.floor) {
      list = list.filter(r => r.floor === params.floor);
    }
    if (params.status_filter) {
      list = list.filter(r => r.monitoring_status.toLowerCase() === params.status_filter.toLowerCase());
    }
    if (params.sort_by) {
      if (params.sort_by === 'room_number') {
        list.sort((a, b) => a.room_number.localeCompare(b.room_number));
      } else if (params.sort_by === 'patient_name') {
        list.sort((a, b) => (a.patient?.name || 'zzz').localeCompare(b.patient?.name || 'zzz'));
      } else if (params.sort_by === 'highest_risk') {
        list.sort((a, b) => b.risk_score - a.risk_score);
      }
    }
    return list;
  }
  const { data } = await http.get('/api/rooms', { params })
  return data
}

export const apiGetRoom = async (id) => {
  if (IS_MOCK) {
    await delay();
    const r = MOCK_ROOMS.find(x => x.id === Number(id));
    if (!r) throw new Error('Room not found');
    return r;
  }
  const { data } = await http.get(`/api/rooms/${id}`)
  return data
}

export const apiCreateRoom = async (payload) => {
  if (IS_MOCK) {
    await delay();
    const r = {
      ...payload,
      id: Date.now(),
      monitoring_status: payload.patient_id ? 'Monitoring' : 'Idle',
      patient: payload.patient_id ? MOCK_PATIENTS.find(p => p.id === payload.patient_id) : null,
      nurses: payload.nurse_ids ? MOCK_USERS.filter(u => payload.nurse_ids.includes(u.id)) : [],
      active_alerts: [],
      risk_score: 0.0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };
    MOCK_ROOMS.push(r);
    return r;
  }
  const { data } = await http.post('/api/rooms', payload)
  return data
}

export const apiUpdateRoom = async (id, payload) => {
  if (IS_MOCK) {
    await delay();
    const idx = MOCK_ROOMS.findIndex(x => x.id === Number(id));
    if (idx === -1) throw new Error('Room not found');
    const existing = MOCK_ROOMS[idx];
    const updated = {
      ...existing,
      ...payload,
      patient: payload.patient_id ? MOCK_PATIENTS.find(p => p.id === payload.patient_id) : null,
      nurses: payload.nurse_ids ? MOCK_USERS.filter(u => payload.nurse_ids.includes(u.id)) : [],
      updated_at: new Date().toISOString()
    };
    MOCK_ROOMS[idx] = updated;
    return updated;
  }
  const { data } = await http.put(`/api/rooms/${id}`, payload)
  return data
}

export const apiDeleteRoom = async (id) => {
  if (IS_MOCK) {
    await delay();
    MOCK_ROOMS = MOCK_ROOMS.filter(x => x.id !== Number(id));
    return { status: 'success' };
  }
  const { data } = await http.delete(`/api/rooms/${id}`)
  return data
}

export const apiAssignPatient = async (roomId, patientId) => {
  if (IS_MOCK) {
    await delay();
    const room = MOCK_ROOMS.find(x => x.id === Number(roomId));
    if (!room) throw new Error('Room not found');
    room.patient_id = patientId;
    room.patient = patientId ? MOCK_PATIENTS.find(p => p.id === patientId) : null;
    room.monitoring_status = patientId ? 'Monitoring' : 'Idle';
    room.updated_at = new Date().toISOString();
    return room;
  }
  const { data } = await http.post(`/api/rooms/${roomId}/assign-patient`, { patient_id: patientId })
  return data
}

export const apiAssignNurses = async (roomId, nurseIds) => {
  if (IS_MOCK) {
    await delay();
    const room = MOCK_ROOMS.find(x => x.id === Number(roomId));
    if (!room) throw new Error('Room not found');
    room.nurses = MOCK_USERS.filter(u => nurseIds.includes(u.id));
    room.updated_at = new Date().toISOString();
    return room;
  }
  const { data } = await http.post(`/api/rooms/${roomId}/assign-nurses`, { nurse_ids: nurseIds })
  return data
}

export const apiAssignServices = async (roomId, services) => {
  if (IS_MOCK) {
    await delay();
    const room = MOCK_ROOMS.find(x => x.id === Number(roomId));
    if (!room) throw new Error('Room not found');
    room.services = services;
    room.updated_at = new Date().toISOString();
    return room;
  }
  const { data } = await http.post(`/api/rooms/${roomId}/assign-services`, { services })
  return data
}

