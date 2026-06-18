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
import { apiGetUsers, apiCreateUser, apiDeactivateUser, apiActivateUser } from '../../api/client'
import { formatDate } from '../../components/utils/time'
import { clsx } from 'clsx'

export default function UserManagementPage() {
  const [users,   setUsers]   = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [filter,  setFilter]  = useState('all')

  useEffect(() => {
    apiGetUsers().then((u) => { setUsers(u); setLoading(false) })
  }, [])

  const filtered = filter === 'all' ? users : users.filter((u) => u.role === filter)

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
        <Button onClick={() => setShowAdd(true)}>
          <Plus size={15} /> Add User
        </Button>
      </div>

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

function AddUserModal({ isOpen, onClose, onCreated }) {
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'doctor', specialty: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

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
