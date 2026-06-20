/**
 * Admin User Management — table-based CRUD for doctor/nurse/admin accounts.
 * Only accessible to admin role.
 */
import { useEffect, useState } from 'react'
import { Plus, UserCheck, UserX } from 'lucide-react'
import Card, { CardHeader } from '../../components/ui/Card'
import Button from '../../components/ui/Button'
import Modal from '../../components/ui/Modal'
import Input, { Select } from '../../components/ui/Input'
import { StatusBadge } from '../../components/ui/Badge'
import { apiGetUsers, apiCreateUser, apiDeactivateUser, apiActivateUser, apiRandomlyAssignPatients } from '../../api/client'
import { formatDate } from '../../components/utils/time'
import { clsx } from 'clsx'

/**
 * User Management page component.
 *
 * Loads all user accounts on mount and allows the admin to filter them by role
 * using a pill-button toolbar. Supports toggling individual accounts between
 * active and inactive states, and opening `AddUserModal` to create new accounts.
 *
 * @returns {JSX.Element} The user management table page.
 */
export default function UserManagementPage() {
  const [users,   setUsers]   = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [filter,  setFilter]  = useState('all')
  const [assigning, setAssigning] = useState(false)
  const [message, setMessage] = useState('')

  const handleAssignPatients = async () => {
    setAssigning(true)
    setMessage('')
    try {
      const res = await apiRandomlyAssignPatients()
      setMessage(res.message || 'Patients randomly assigned successfully!')
    } catch (err) {
      setMessage(err?.response?.data?.detail || 'Failed to assign patients')
    } finally {
      setAssigning(false)
    }
  }

  useEffect(() => {
    apiGetUsers().then((u) => { setUsers(u); setLoading(false) })
  }, [])

  const filtered = filter === 'all' ? users : users.filter((u) => u.role === filter)

  /**
   * Toggles a user's active/inactive status.
   *
   * Calls `apiDeactivateUser` if the user is currently active, or
   * `apiActivateUser` if inactive, then updates the local users list with the
   * returned updated user object.
   *
   * @param {object} user - The user object whose status should be toggled.
   * @returns {Promise<void>}
   */
  const toggleActive = async (user) => {
    const updated = user.is_active
      ? await apiDeactivateUser(user.id)
      : await apiActivateUser(user.id)
    setUsers((prev) => prev.map((u) => u.id === updated.id ? updated : u))
  }

  const ROLE_BADGE = {
    doctor: 'bg-teal-100 text-teal-700',
    nurse:  'bg-navy-100 text-navy-700',
    admin:  'bg-purple-100 text-purple-700',
  }

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading font-bold text-2xl text-navy-900">User Management</h1>
          <p className="text-navy-400 text-sm">{users.filter((u) => u.is_active).length} active accounts</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={handleAssignPatients} loading={assigning}>
            Randomize Assignments
          </Button>
          <Button onClick={() => setShowAdd(true)}>
            <Plus size={15} /> Add User
          </Button>
        </div>
      </div>

      {message && (
        <div className={clsx(
          "p-3 rounded-lg text-sm font-medium border",
          message.toLowerCase().includes('fail') ? "bg-red-50 text-red-700 border-red-200" : "bg-teal-50 text-teal-700 border-teal-200"
        )}>
          {message}
        </div>
      )}

      {/* Role filter */}
      <div className="flex gap-2">
        {['all', 'doctor', 'nurse', 'admin'].map((r) => (
          <button
            key={r}
            onClick={() => setFilter(r)}
            className={clsx(
              'px-3 py-1.5 rounded-lg text-sm font-medium capitalize transition-colors',
              filter === r ? 'bg-navy-900 text-white' : 'bg-white text-navy-500 border border-navy-200 hover:border-navy-400',
            )}
          >
            {r === 'all' ? 'All' : r + 's'}
          </button>
        ))}
      </div>

      <Card padded={false}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-navy-100 bg-navy-50">
              {['Name', 'Email', 'Role', 'Specialty', 'Status', 'Created', ''].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-navy-500 uppercase tracking-wide">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-navy-50">
            {loading
              ? Array(4).fill(0).map((_, i) => (
                  <tr key={i}><td colSpan={7} className="px-4 py-3"><div className="h-5 bg-navy-100 rounded animate-pulse" /></td></tr>
                ))
              : filtered.map((u) => (
                  <tr key={u.id} className={clsx('transition-colors', !u.is_active && 'opacity-50')}>
                    <td className="px-4 py-3 font-medium text-navy-900">{u.name}</td>
                    <td className="px-4 py-3 text-navy-600 font-mono text-xs">{u.email}</td>
                    <td className="px-4 py-3">
                      <span className={clsx('px-2 py-0.5 rounded-full text-xs font-semibold capitalize', ROLE_BADGE[u.role])}>
                        {u.role}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-navy-500">{u.specialty || '—'}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={u.is_active ? 'active' : 'inactive'} />
                    </td>
                    <td className="px-4 py-3 text-navy-400 text-xs">{formatDate(u.created_at)}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => toggleActive(u)}
                        title={u.is_active ? 'Deactivate' : 'Activate'}
                        className={clsx(
                          'p-1.5 rounded-lg transition-colors',
                          u.is_active
                            ? 'text-red-400 hover:bg-red-50 hover:text-red-600'
                            : 'text-green-500 hover:bg-green-50 hover:text-green-700',
                        )}
                      >
                        {u.is_active ? <UserX size={15} /> : <UserCheck size={15} />}
                      </button>
                    </td>
                  </tr>
                ))
            }
          </tbody>
        </table>
      </Card>

      <AddUserModal
        isOpen={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={(u) => { setUsers((prev) => [u, ...prev]); setShowAdd(false) }}
      />
    </div>
  )
}

/**
 * Modal dialog for creating a new user account.
 *
 * Manages a controlled form with name, email, password, role, and optional
 * specialty (shown only for the doctor role). On success calls `onCreated`
 * with the new user object so the parent prepends it to the table.
 *
 * @param {object}   props
 * @param {boolean}  props.isOpen    - Whether the modal is currently open.
 * @param {Function} props.onClose   - Callback to close the modal without saving.
 * @param {Function} props.onCreated - Callback invoked with the created user object.
 * @returns {JSX.Element}
 */
function AddUserModal({ isOpen, onClose, onCreated }) {
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'doctor', specialty: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  /**
   * Curried field-setter factory for the controlled form.
   *
   * Returns a change-event handler that updates the named `field` in the
   * `form` state object while preserving all other field values.
   *
   * @param {string} field - The form field key to update.
   * @returns {Function} An `onChange` handler compatible with input/select elements.
   */
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  /**
   * Handles the "Create Account" form submission.
   *
   * Calls `apiCreateUser` with the current form state and, on success,
   * forwards the new user to `onCreated`. Displays a server error message
   * if the request fails.
   *
   * @param {React.FormEvent<HTMLFormElement>} e - The form submit event.
   * @returns {Promise<void>}
   */
  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const u = await apiCreateUser(form)
      onCreated(u)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to create user')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Add New User"
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button form="add-user-form" type="submit" loading={loading}>Create Account</Button>
      </>}
    >
      <form id="add-user-form" onSubmit={handleSubmit} className="space-y-4">
        <Input label="Full Name" required value={form.name} onChange={set('name')} />
        <Input label="Email" type="email" required value={form.email} onChange={set('email')} />
        <Input label="Password" type="password" required value={form.password} onChange={set('password')} hint="Minimum 8 characters" />
        <Select label="Role" value={form.role} onChange={set('role')}>
          <option value="doctor">Doctor</option>
          <option value="nurse">Nurse</option>
          <option value="admin">Admin</option>
        </Select>
        {form.role === 'doctor' && (
          <Input label="Specialty" value={form.specialty} onChange={set('specialty')} placeholder="e.g. Cardiology" />
        )}
        {error && <p className="text-red-600 text-sm">{error}</p>}
      </form>
    </Modal>
  )
}
