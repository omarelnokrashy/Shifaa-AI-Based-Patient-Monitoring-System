/**
 * Mock data — realistic clinical dataset used when VITE_DATA_MODE=mock.
 * Structured to mirror the exact shapes returned by the FastAPI backend,
 * so switching to live data is a one-line change in api/client.js.
 */

export const MOCK_PATIENTS = [
  {
    id: 1, name: 'Ahmad Hassan', dob: '1978-04-12', gender: 'Male',
    blood_type: 'O+', phone: '555-0101', created_at: '2025-01-15T10:30:00',
    diagnoses: [
      { id: 1, description: 'Type 2 Diabetes Mellitus', icd10_code: 'E11', diagnosed_on: '2022-03-10', is_active: true, severity: 'moderate' },
      { id: 2, description: 'Hypertension', icd10_code: 'I10', diagnosed_on: '2021-06-22', is_active: true, severity: 'mild' },
    ],
    medications: [
      { id: 1, drug_name: 'Metformin', dose: '500mg twice daily', start_date: '2022-03-15', is_active: true },
      { id: 2, drug_name: 'Amlodipine', dose: '5mg once daily', start_date: '2021-07-01', is_active: true },
    ],
    lab_results: [
      { id: 1, test_name: 'HbA1c', value: 7.8, unit: '%', reference: '4.0-5.6', test_date: '2026-05-10', is_abnormal: true },
      { id: 2, test_name: 'Fasting Blood Glucose', value: 142, unit: 'mg/dL', reference: '70-100', test_date: '2026-05-10', is_abnormal: true },
      { id: 3, test_name: 'Creatinine', value: 1.1, unit: 'mg/dL', reference: '0.6-1.2', test_date: '2026-04-20', is_abnormal: false },
    ],
    allergies: [
      { id: 1, allergen: 'Penicillin', reaction: 'Anaphylaxis', severity: 'severe' },
    ],
    visits: [
      { id: 1, visit_date: '2026-05-10', chief_complaint: 'Routine diabetic follow-up', notes: 'HbA1c elevated — increased Metformin dose discussed.' },
    ],
  },
  {
    id: 2, name: 'Sara Ahmed', dob: '1990-06-20', gender: 'Female',
    blood_type: 'A+', phone: '555-0202', created_at: '2025-02-01T09:00:00',
    diagnoses: [
      { id: 3, description: 'Epilepsy', icd10_code: 'G40', diagnosed_on: '2020-01-15', is_active: true, severity: 'moderate' },
    ],
    medications: [
      { id: 3, drug_name: 'Levetiracetam', dose: '500mg twice daily', start_date: '2020-02-01', is_active: true },
    ],
    lab_results: [
      { id: 4, test_name: 'Hemoglobin', value: 11.8, unit: 'g/dL', reference: '12.0-16.0', test_date: '2026-04-15', is_abnormal: true },
    ],
    allergies: [],
    visits: [
      { id: 2, visit_date: '2026-06-01', chief_complaint: 'Seizure frequency increased', notes: 'Three events in past month. Considering dose adjustment.' },
    ],
  },
  {
    id: 3, name: 'Khaled Ibrahim', dob: '1955-11-30', gender: 'Male',
    blood_type: 'B+', phone: '555-0303', created_at: '2025-03-10T11:00:00',
    diagnoses: [
      { id: 4, description: 'Atrial Fibrillation', icd10_code: 'I48', diagnosed_on: '2023-08-05', is_active: true, severity: 'severe' },
      { id: 5, description: 'Chronic Kidney Disease Stage 3', icd10_code: 'N18.3', diagnosed_on: '2022-12-01', is_active: true, severity: 'moderate' },
    ],
    medications: [
      { id: 4, drug_name: 'Apixaban', dose: '5mg twice daily', start_date: '2023-08-10', is_active: true },
      { id: 5, drug_name: 'Furosemide', dose: '40mg once daily', start_date: '2023-09-01', is_active: true },
    ],
    lab_results: [
      { id: 5, test_name: 'Creatinine', value: 2.4, unit: 'mg/dL', reference: '0.6-1.2', test_date: '2026-06-10', is_abnormal: true },
    ],
    allergies: [{ id: 2, allergen: 'Aspirin', reaction: 'GI Bleeding', severity: 'severe' }],
    visits: [],
  },
  {
    id: 4, name: 'Mona Nasser', dob: '1965-03-18', gender: 'Female',
    blood_type: 'AB-', phone: '555-0404', created_at: '2025-04-05T14:00:00',
    diagnoses: [
      { id: 6, description: 'Hypothyroidism', icd10_code: 'E03', diagnosed_on: '2019-05-10', is_active: true, severity: 'mild' },
    ],
    medications: [
      { id: 6, drug_name: 'Levothyroxine', dose: '50mcg once daily', start_date: '2019-05-15', is_active: true },
    ],
    lab_results: [
      { id: 6, test_name: 'TSH', value: 0.3, unit: 'mIU/L', reference: '0.4-4.0', test_date: '2026-05-28', is_abnormal: true },
    ],
    allergies: [],
    visits: [],
  },
]

export const MOCK_ALERTS = [
  {
    id: 101, patient_id: 3, patient_name: 'Khaled Ibrahim',
    alert_type: 'arrhythmia', severity: 'high',
    details: { stage1: 'Abnormal', stage2_class: 'AF', stage1_confidence: 0.94 },
    created_at: new Date(Date.now() - 5 * 60000).toISOString(),
    acknowledged: false,
  },
  {
    id: 102, patient_id: 2, patient_name: 'Sara Ahmed',
    alert_type: 'seizure', severity: 'critical',
    details: { status: 'SEIZURE', gate_score: 0.87, mode: 'monitor' },
    created_at: new Date(Date.now() - 12 * 60000).toISOString(),
    acknowledged: false,
  },
  {
    id: 103, patient_id: 1, patient_name: 'Ahmad Hassan',
    alert_type: 'fall', severity: 'critical',
    details: { fall_detected: true, fall_probability: 0.97 },
    created_at: new Date(Date.now() - 45 * 60000).toISOString(),
    acknowledged: true,
  },
]

export const MOCK_USERS = [
  { id: 1, name: 'Dr. Ahmed Hassan', email: 'doctor@hospital.com', role: 'doctor', specialty: 'Internal Medicine', is_active: true, created_at: '2025-01-01T00:00:00' },
  { id: 2, name: 'Nurse Sara Mohamed', email: 'nurse@hospital.com', role: 'nurse', specialty: null, is_active: true, created_at: '2025-01-02T00:00:00' },
  { id: 3, name: 'Admin Omar Nour', email: 'admin@hospital.com', role: 'admin', specialty: null, is_active: true, created_at: '2025-01-03T00:00:00' },
  { id: 4, name: 'Dr. Layla Khalid', email: 'layla@hospital.com', role: 'doctor', specialty: 'Neurology', is_active: false, created_at: '2025-02-01T00:00:00' },
]

export const MOCK_SERVICE_HEALTH = {
  arrhythmia: { status: 'ok', models_loaded: true, device: 'cuda' },
  fall:       { status: 'ok', models_loaded: true, active_sessions: 2 },
  seizure:    { status: 'ok', active_sessions: 1, alive_processes: 1 },
  main:       { status: 'ok' },
}

/** Generate a plausible 12-lead ECG waveform snippet for display */
export function generateMockECG(samples = 500) {
  const out = []
  for (let i = 0; i < samples; i++) {
    const t = (i / samples) * Math.PI * 8
    const qrs = i % 80 < 10 ? Math.sin((i % 80) * 0.6) * 1.8 : 0
    out.push({
      t: i,
      I:   Math.sin(t * 0.5) * 0.3 + qrs + (Math.random() - 0.5) * 0.08,
      II:  Math.sin(t * 0.5) * 0.5 + qrs * 1.2 + (Math.random() - 0.5) * 0.08,
      V1:  Math.sin(t * 0.5) * 0.2 + qrs * 0.9 + (Math.random() - 0.5) * 0.06,
      V5:  Math.sin(t * 0.5) * 0.6 + qrs * 1.5 + (Math.random() - 0.5) * 0.06,
    })
  }
  return out
}

export const MOCK_MONITORING_SESSIONS = [
  {
    room_id: '2', patient_id: 2, patient_name: 'Sara Ahmed',
    type: 'seizure', mode: 'monitor', status: 'SEIZURE',
    gate_score: 0.87, alert: true, alert_latched: true,
    started_at: new Date(Date.now() - 8 * 60000).toISOString(),
  },
  {
    room_id: '1', patient_id: 1, patient_name: 'Ahmad Hassan',
    type: 'fall', status: 'NORMAL',
    fall_probability: 0.12,
    started_at: new Date(Date.now() - 30 * 60000).toISOString(),
  },
]
