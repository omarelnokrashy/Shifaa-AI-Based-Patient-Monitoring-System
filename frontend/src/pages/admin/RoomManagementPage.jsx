/**
 * RoomManagementPage — Administration console for rooms.
 * Allows creation, updating, and deprovisioning of hospital rooms,
 * patient mapping, nurse selection, and service toggling.
 */
import { useEffect, useState } from 'react'
import { Plus, Edit2, Trash2, Shield, Radio, Check, X, Layers } from 'lucide-react'
import Card from '../../components/ui/Card'
import Button from '../../components/ui/Button'
import Input, { Select } from '../../components/ui/Input'
import Modal from '../../components/ui/Modal'
import { StatusBadge } from '../../components/ui/Badge'
import {
  apiGetRooms,
  apiCreateRoom,
  apiUpdateRoom,
  apiDeleteRoom,
  apiGetPatients,
  apiGetUsers,
} from '../../api/client'

export default function RoomManagementPage() {
  const [rooms, setRooms] = useState([])
  const [patients, setPatients] = useState([])
  const [nurses, setNurses] = useState([])
  const [loading, setLoading] = useState(true)
  
  // Modal states
  const [modalOpen, setModalOpen] = useState(false)
  const [editingRoom, setEditingRoom] = useState(null) // null = Create Mode, otherwise Room object
  const [error, setError] = useState('')

  // Form states
  const [roomNumber, setRoomNumber] = useState('')
  const [roomName, setRoomName] = useState('')
  const [floor, setFloor] = useState('1')
  const [patientId, setPatientId] = useState('')
  const [selectedServices, setSelectedServices] = useState({ ecg: false, seizure: false, fall: false })
  const [selectedNurses, setSelectedNurses] = useState([])

  const loadData = async () => {
    try {
      setLoading(true)
      const [r, p, u] = await Promise.all([
        apiGetRooms(),
        apiGetPatients(),
        apiGetUsers(),
      ])
      setRooms(r)
      setPatients(p)
      // Filter out only active nurses
      const activeNurses = u.filter(
        (x) => x.role === 'nurse' && x.is_active !== false
      )
      setNurses(activeNurses)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleOpenCreateModal = () => {
    setEditingRoom(null)
    setRoomNumber('')
    setRoomName('')
    setFloor('1')
    setPatientId('')
    setSelectedServices({ ecg: false, seizure: false, fall: false })
    setSelectedNurses([])
    setError('')
    setModalOpen(true)
  }

  const handleOpenEditModal = (room) => {
    setEditingRoom(room)
    setRoomNumber(room.room_number)
    setRoomName(room.room_name || '')
    setFloor(room.floor || '1')
    setPatientId(room.patient_id ? String(room.patient_id) : '')
    
    // Services
    const svcs = { ecg: false, seizure: false, fall: false }
    room.services.forEach((s) => {
      if (s.toLowerCase() === 'ecg') svcs.ecg = true
      if (s.toLowerCase() === 'seizure') svcs.seizure = true
      if (s.toLowerCase() === 'fall') svcs.fall = true
    })
    setSelectedServices(svcs)

    // Nurses
    setSelectedNurses(room.nurses.map((n) => n.id))
    setError('')
    setModalOpen(true)
  }

  const handleToggleService = (svc) => {
    setSelectedServices((prev) => ({ ...prev, [svc]: !prev[svc] }))
  }

  const handleToggleNurse = (nurseId) => {
    setSelectedNurses((prev) =>
      prev.includes(nurseId)
        ? prev.filter((id) => id !== nurseId)
        : [...prev, nurseId]
    )
  }

  const handleSave = async (e) => {
    e.preventDefault()
    setError('')

    if (!roomNumber.trim()) {
      setError('Room Number is required.')
      return
    }

    const payload = {
      room_number: roomNumber.trim(),
      room_name: roomName.trim() || null,
      floor: floor,
      patient_id: patientId ? Number(patientId) : null,
      services: Object.keys(selectedServices).filter((k) => selectedServices[k]),
      nurse_ids: selectedNurses,
    }

    try {
      if (editingRoom) {
        await apiUpdateRoom(editingRoom.id, payload)
      } else {
        await apiCreateRoom(payload)
      }
      setModalOpen(false)
      loadData()
    } catch (err) {
      setError(err.response?.data?.detail || 'An error occurred while saving.')
    }
  }

  const handleDelete = async (room) => {
    if (window.confirm(`Are you sure you want to delete Room ${room.room_number}?`)) {
      try {
        await apiDeleteRoom(room.id)
        loadData()
      } catch (err) {
        alert('Failed to delete room.')
      }
    }
  }

  if (loading && rooms.length === 0) {
    return <div className="text-navy-500 p-8 text-center">Loading Room configuration...</div>
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading font-bold text-2xl text-navy-900 flex items-center gap-2">
            <Layers className="text-teal-600" /> Room Configuration Management
          </h1>
          <p className="text-navy-400 text-sm">
            Deprovision, initialize, and configure physical ward rooms and assignments.
          </p>
        </div>
        <Button variant="primary" onClick={handleOpenCreateModal} className="flex items-center gap-1.5">
          <Plus size={16} /> Create Room
        </Button>
      </div>

      {/* Room Table Card */}
      <Card className="overflow-hidden border border-navy-100">
        <table className="w-full text-left border-collapse text-sm">
          <thead>
            <tr className="bg-navy-50 text-navy-600 font-semibold border-b border-navy-100">
              <th className="px-6 py-4">Room No.</th>
              <th className="px-6 py-4">Room Name</th>
              <th className="px-6 py-4">Floor</th>
              <th className="px-6 py-4">Patient</th>
              <th className="px-6 py-4">Services</th>
              <th className="px-6 py-4">Assigned Nurse(s)</th>
              <th className="px-6 py-4 text-center">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-navy-100 text-navy-800">
            {rooms.length === 0 ? (
              <tr>
                <td colSpan="7" className="px-6 py-12 text-center text-navy-400 font-medium">
                  No rooms configured yet. Click "Create Room" to begin.
                </td>
              </tr>
            ) : (
              rooms.map((room) => (
                <tr key={room.id} className="hover:bg-navy-50/50 transition-colors">
                  <td className="px-6 py-4 font-bold text-teal-700">{room.room_number}</td>
                  <td className="px-6 py-4 font-semibold">{room.room_name || '—'}</td>
                  <td className="px-6 py-4">Floor {room.floor || '1'}</td>
                  <td className="px-6 py-4">
                    {room.patient ? (
                      <div>
                        <p className="font-semibold text-navy-900">{room.patient.name}</p>
                        <p className="text-xs text-navy-400">ID: {room.patient.id}</p>
                      </div>
                    ) : (
                      <span className="text-navy-400 text-xs italic">No Patient</span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex gap-1.5 flex-wrap">
                      {room.services.length === 0 ? (
                        <span className="text-navy-300 text-xs italic">None</span>
                      ) : (
                        room.services.map((s) => (
                          <span
                            key={s}
                            className="px-2 py-0.5 rounded bg-teal-50 border border-teal-200 text-teal-700 text-[10px] font-bold uppercase tracking-wider"
                          >
                            {s}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    {room.nurses.length === 0 ? (
                      <span className="text-navy-300 text-xs italic">Unassigned</span>
                    ) : (
                      <div className="flex flex-col gap-0.5">
                        {room.nurses.map((n) => (
                          <span key={n.id} className="font-medium text-xs">
                            {n.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-6 py-4 text-center">
                    <div className="flex items-center justify-center gap-2">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleOpenEditModal(room)}
                        title="Edit Room Configuration"
                      >
                        <Edit2 size={14} className="text-navy-600" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(room)}
                        title="Delete Room"
                      >
                        <Trash2 size={14} className="text-red-500" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>

      {/* Create / Edit Dialog */}
      <Modal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingRoom ? `Edit Room ${editingRoom.room_number}` : 'Create Room Configuration'}
        size="lg"
        footer={
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleSave}>
              Save Room
            </Button>
          </div>
        }
      >
        <form onSubmit={handleSave} className="space-y-4">
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-xs font-semibold">
              {error}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Room Number"
              placeholder="e.g. 204"
              value={roomNumber}
              onChange={(e) => setRoomNumber(e.target.value)}
              required
            />
            <Input
              label="Room Name / Label"
              placeholder="e.g. ICU Bed A"
              value={roomName}
              onChange={(e) => setRoomName(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Select
              label="Floor Location"
              value={floor}
              onChange={(e) => setFloor(e.target.value)}
            >
              <option value="1">Floor 1</option>
              <option value="2">Floor 2</option>
              <option value="3">Floor 3</option>
              <option value="4">Floor 4</option>
            </Select>

            <Select
              label="Assigned Patient"
              value={patientId}
              onChange={(e) => setPatientId(e.target.value)}
            >
              <option value="">-- No Patient Assigned --</option>
              {patients.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} (ID: {p.id})
                </option>
              ))}
            </Select>
          </div>

          {/* Enabled Services Selection */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-navy-700 uppercase tracking-wide">
              Enabled Monitoring Services
            </label>
            <div className="grid grid-cols-3 gap-3">
              {['ecg', 'seizure', 'fall'].map((svc) => (
                <div
                  key={svc}
                  onClick={() => handleToggleService(svc)}
                  className={`p-3 border rounded-xl flex items-center justify-between cursor-pointer transition-all ${
                    selectedServices[svc]
                      ? 'border-teal-500 bg-teal-50/50 text-teal-900 font-bold'
                      : 'border-navy-100 hover:border-navy-300 bg-white text-navy-600'
                  }`}
                >
                  <span className="uppercase text-xs tracking-wider">{svc === 'ecg' ? 'ECG/Arrhythmia' : svc}</span>
                  <div
                    className={`w-4 h-4 rounded-full border flex items-center justify-center ${
                      selectedServices[svc] ? 'bg-teal-600 border-teal-600 text-white' : 'border-navy-300'
                    }`}
                  >
                    {selectedServices[svc] && <Check size={10} strokeWidth={3} />}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Assigned Nurses checkboxes */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-navy-700 uppercase tracking-wide">
              Assigned Nurse(s)
            </label>
            {nurses.length === 0 ? (
              <p className="text-navy-400 text-xs italic">No nurses available in system.</p>
            ) : (
              <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto border border-navy-100 rounded-xl p-3 bg-navy-50/20">
                {nurses.map((n) => {
                  const isChecked = selectedNurses.includes(n.id)
                  return (
                    <div
                      key={n.id}
                      onClick={() => handleToggleNurse(n.id)}
                      className={`p-2.5 rounded-lg border flex items-center gap-2.5 cursor-pointer transition-all ${
                        isChecked
                          ? 'border-teal-500 bg-teal-50/30 font-semibold'
                          : 'border-navy-100 hover:bg-white bg-white/70'
                      }`}
                    >
                      <div
                        className={`w-4 h-4 rounded flex items-center justify-center border ${
                          isChecked ? 'bg-teal-600 border-teal-600 text-white' : 'border-navy-300'
                        }`}
                      >
                        {isChecked && <Check size={10} strokeWidth={3} />}
                      </div>
                      <div className="leading-tight">
                        <p className="text-xs font-medium text-navy-800">{n.name}</p>
                        <p className="text-[10px] text-navy-400">{n.email}</p>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </form>
      </Modal>
    </div>
  )
}
