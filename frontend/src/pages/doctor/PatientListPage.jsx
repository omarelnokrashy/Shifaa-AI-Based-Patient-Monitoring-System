/**
 * Patient List — full-page searchable patient browser.
 * Mirrors the original sidebar pattern but expanded into a proper data table
 * with inline quick-stats (active diagnoses, abnormal labs, allergy flag).
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, AlertCircle } from 'lucide-react'
import Card from '../../components/ui/Card'
import Button from '../../components/ui/Button'
import Input from '../../components/ui/Input'
import Modal from '../../components/ui/Modal'
import { apiGetPatients, apiCreatePatient } from '../../api/client'
import { calcAge, formatDate } from '../../components/utils/time'
import { clsx } from 'clsx'
import useAuthStore from '../../store/authStore'

/**
 * Patient List page component.
 *
 * Renders a searchable, paginated table of all patients. Debounces the search
 * input so the API is only called when the query changes. Provides an "Add
 * Patient" button that opens `AddPatientModal` and prepends the newly created
 * patient to the list on success.
 *
 * @returns {JSX.Element} The patient list table page.
 */
export default function PatientListPage() {
  const navigate = useNavigate()
  const [patients, setPatients] = useState([])
  const [search,   setSearch]   = useState('')
  const [loading,  setLoading]  = useState(true)
  const [showAdd,  setShowAdd]  = useState(false)
  const user = useAuthStore((s) => s.user)
  const basePath = user?.role === 'nurse' ? '/nurse' : '/doctor'

  useEffect(() => {
    setLoading(true)
    apiGetPatients(search).then((p) => { setPatients(p); setLoading(false) })
  }, [search])

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading font-bold text-2xl text-navy-900">Patients</h1>
          <p className="text-navy-400 text-sm">{patients.length} total</p>
        </div>
        <Button onClick={() => setShowAdd(true)}>
          <Plus size={15} /> Add Patient
        </Button>
      </div>

      {/* Search */}
      <Input
        placeholder="Search by name…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="max-w-xs"
      />

      {/* Table */}
      <Card padded={false}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-navy-100 bg-navy-50">
              {['Patient', 'Age / Gender', 'Blood Type', 'Active Diagnoses', 'Alerts', ''].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-navy-500 uppercase tracking-wide">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-navy-50">
            {loading
              ? Array(5).fill(0).map((_, i) => (
                  <tr key={i}><td colSpan={6} className="px-4 py-3"><div className="h-6 bg-navy-100 rounded animate-pulse" /></td></tr>
                ))
              : patients.map((p) => (
                  <PatientRow key={p.id} patient={p} onClick={() => navigate(`${basePath}/patients/${p.id}`)} />
                ))
            }
          </tbody>
        </table>
        {!loading && !patients.length && (
          <p className="text-center py-10 text-navy-400 text-sm">No patients found.</p>
        )}
      </Card>

      {/* Add patient modal */}
      <AddPatientModal
        isOpen={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={(p) => { setPatients((prev) => [p, ...prev]); setShowAdd(false) }}
      />
    </div>
  )
}

/**
 * Table row representing a single patient with quick-stat indicators.
 *
 * Displays the patient avatar, name, ID, age/gender, blood type, active
 * diagnosis count, and flag icons for abnormal lab results or allergies.
 * Clicking anywhere on the row triggers `onClick`.
 *
 * @param {object}   props
 * @param {object}   props.patient - Patient object from the API.
 * @param {Function} props.onClick - Callback invoked when the row is clicked.
 * @returns {JSX.Element}
 */
function PatientRow({ patient, onClick }) {
  const activeDxCount = (patient.diagnoses || []).filter((d) => d.is_active).length
  const activeAlertsCount = (patient.alerts || []).length

  return (
    <tr
      onClick={onClick}
      className="hover:bg-navy-50 cursor-pointer transition-colors group"
    >
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-teal-100 flex items-center justify-center text-teal-700 font-semibold text-xs shrink-0">
            {patient.name.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase()}
          </div>
          <div>
            <p className="font-medium text-navy-900 group-hover:text-teal-700 transition-colors">{patient.name}</p>
            <p className="text-xs text-navy-400">ID #{patient.id}</p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3 text-navy-600">
        {calcAge(patient.dob)} · {patient.gender}
      </td>
      <td className="px-4 py-3">
        <span className="px-2 py-0.5 rounded bg-navy-100 text-navy-700 text-xs font-mono font-semibold">
          {patient.blood_type || '—'}
        </span>
      </td>
      <td className="px-4 py-3">
        {activeDxCount > 0 ? (
          <span className="text-navy-700 font-medium">{activeDxCount}</span>
        ) : <span className="text-navy-300">—</span>}
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          {activeAlertsCount > 0 ? (
            <span className="text-red-600 font-semibold flex items-center gap-1">
              <AlertCircle size={14} className="animate-pulse" /> {activeAlertsCount} Active
            </span>
          ) : (
            <span className="text-green-600 text-xs font-medium">✓ Clear</span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-right">
        <span className="text-teal-600 text-xs font-medium opacity-0 group-hover:opacity-100 transition-opacity">
          View →
        </span>
      </td>
    </tr>
  )
}

/**
 * Modal dialog for registering a new patient.
 *
 * Controls a controlled form with name, date of birth, gender, blood type,
 * and phone fields. On successful submission calls `onCreated` with the
 * newly created patient object so the parent can prepend it to the list.
 *
 * @param {object}   props
 * @param {boolean}  props.isOpen    - Whether the modal is visible.
 * @param {Function} props.onClose   - Callback to close the modal without saving.
 * @param {Function} props.onCreated - Callback invoked with the new patient after creation.
 * @returns {JSX.Element}
 */
function AddPatientModal({ isOpen, onClose, onCreated }) {
  const [form, setForm] = useState({ name: '', dob: '', gender: 'Male', blood_type: 'O+', phone: '' })
  const [loading, setLoading] = useState(false)

  /**
   * Curried field-setter factory for the controlled form.
   *
   * Returns a change-event handler that updates the named `field` in the
   * `form` state object while preserving all other field values.
   *
   * @param {string} field - The form field key to update.
   * @returns {Function} An `onChange` handler compatible with input elements.
   */
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  /**
   * Handles the "Register" form submission.
   *
   * Calls `apiCreatePatient` with the current form state and, on success,
   * forwards the returned patient object to `onCreated`.
   *
   * @param {React.FormEvent<HTMLFormElement>} e - The form submit event.
   * @returns {Promise<void>}
   */
  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      const p = await apiCreatePatient(form)
      onCreated(p)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Register New Patient"
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button form="add-patient-form" type="submit" loading={loading}>Register</Button>
      </>}
    >
      <form id="add-patient-form" onSubmit={handleSubmit} className="grid grid-cols-2 gap-4">
        <Input label="Full Name" className="col-span-2" required value={form.name} onChange={set('name')} />
        <Input label="Date of Birth" type="date" required value={form.dob} onChange={set('dob')} />
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-navy-700 uppercase tracking-wide">Gender</label>
          <select value={form.gender} onChange={set('gender')} className="px-3 py-2.5 text-sm bg-white border border-navy-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500">
            <option>Male</option><option>Female</option><option>Other</option>
          </select>
        </div>
        <Input label="Blood Type" value={form.blood_type} onChange={set('blood_type')} />
        <Input label="Phone" value={form.phone} onChange={set('phone')} />
      </form>
    </Modal>
  )
}
