/**
 * Live Monitoring View — Redesigned as a Hospital Central Monitoring Station.
 *
 * Each room is displayed as a card showing:
 *  - Room number, floor, patient name/ID, assigned nurse(s).
 *  - Current telemetry status: Idle, Monitoring, Warning, Critical Alert, Offline.
 *  - Clinical service icons: Heart (ECG), Brain (Seizure), ArrowDown/Triangle (Fall).
 *  - Blinking alarm panels for active alerts.
 *  - Updates occur in real-time via WebSocket events for the affected card only.
 */
import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Heart, Brain, AlertTriangle, Search, Filter, SortAsc,
  User, CheckCircle2, ShieldAlert, AlertCircle, RefreshCw, Eye
} from 'lucide-react'
import Card from '../../components/ui/Card'
import Button from '../../components/ui/Button'
import { StatusBadge } from '../../components/ui/Badge'
import useAuthStore from '../../store/authStore'
import { apiGetRooms, apiGetUsers } from '../../api/client'

const IS_MOCK = import.meta.env.VITE_DATA_MODE !== 'live'
const WS_BASE = import.meta.env.VITE_WS_URL || 'ws://localhost:8000'

export default function LiveMonitoringPage() {
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)

  // State
  const [rooms, setRooms] = useState([])
  const [nursesList, setNursesList] = useState([])
  const [loading, setLoading] = useState(true)

  // Filtering & Sorting State
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedService, setSelectedService] = useState('')
  const [selectedNurse, setSelectedNurse] = useState('')
  const [selectedStatus, setSelectedStatus] = useState('')
  const [selectedFloor, setSelectedFloor] = useState('')
  const [sortBy, setSortBy] = useState('room_number')

  const wsRef = useRef(null)

  // Fetch initial rooms and nurses list
  const loadInitialData = async () => {
    try {
      setLoading(true)
      const params = {
        sort_by: sortBy,
        service: selectedService,
        nurse_id: selectedNurse ? Number(selectedNurse) : undefined,
        floor: selectedFloor,
        status_filter: selectedStatus
      }
      
      const promises = [apiGetRooms(params)]
      if (user?.role === 'admin' || user?.role === 'doctor') {
        promises.push(apiGetUsers())
      }
      
      const results = await Promise.all(promises)
      const roomsData = results[0]
      const usersData = results[1] || []
      
      setRooms(roomsData)
      if (user?.role === 'admin' || user?.role === 'doctor') {
        setNursesList(usersData.filter(u => u.role === 'nurse'))
      }
    } catch (err) {
      console.error("Failed to load live monitor rooms:", err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadInitialData()
  }, [selectedService, selectedNurse, selectedStatus, selectedFloor, sortBy])

  // Real-time WebSocket connection for room updates
  useEffect(() => {
    if (IS_MOCK || !token) {
      // Simulate real-time room updates on a timer in mock mode
      const timer = setInterval(() => {
        setRooms((prevRooms) => {
          if (prevRooms.length === 0) return prevRooms
          const nextRooms = [...prevRooms]
          // Pick a random room to transition its status
          const idx = Math.floor(Math.random() * nextRooms.length)
          const target = { ...nextRooms[idx] }

          if (target.patient) {
            // Toggle between alert states and normal monitoring
            if (target.monitoring_status === 'Monitoring') {
              const types = ['fall', 'seizure', 'arrhythmia']
              const selectedType = types[Math.floor(Math.random() * types.length)]
              target.monitoring_status = 'Critical Alert'
              target.risk_score = 0.92
              target.active_alerts = [
                {
                  id: Date.now(),
                  alert_type: selectedType,
                  severity: 'critical',
                  details: { message: `Simulated live ${selectedType} alert` },
                  created_at: new Date().toISOString()
                }
              ]
            } else {
              target.monitoring_status = 'Monitoring'
              target.risk_score = 0.0
              target.active_alerts = []
            }
          }
          nextRooms[idx] = target
          return nextRooms
        })
      }, 16000)

      return () => clearInterval(timer)
    }

    // Live Mode: Connect to alerts WebSocket to catch room_update frames
    let cancelled = false
    const connectWS = () => {
      if (cancelled) return
      const ws = new WebSocket(`${WS_BASE}/api/ws/alerts?token=${token}`)
      wsRef.current = ws

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data)
          if (event.type === 'room_update') {
            const updatedRoom = event.room_data
            if (updatedRoom) {
              setRooms((prevRooms) => {
                // If it is already in our list, replace it
                const index = prevRooms.findIndex(r => r.id === updatedRoom.id)
                if (index !== -1) {
                  const nextRooms = [...prevRooms]
                  nextRooms[index] = updatedRoom
                  return nextRooms
                }
                // If nurse user, only show rooms they are assigned to
                if (user?.role === 'nurse') {
                  const isAssigned = updatedRoom.nurses.some(n => n.id === Number(user.id))
                  if (!isAssigned) return prevRooms
                }
                return [...prevRooms, updatedRoom]
              })
            }
          } else if (event.type === 'room_delete') {
            setRooms((prevRooms) => prevRooms.filter(r => r.id !== event.room_id))
          }
        } catch (err) {
          console.error("Failed to parse websocket message:", err)
        }
      }

      ws.onclose = () => {
        if (!cancelled) {
          setTimeout(connectWS, 3000)
        }
      }
    }

    connectWS()

    return () => {
      cancelled = true
      wsRef.current?.close()
    }
  }, [token, user])

  // Instant local search filter (names, IDs, room number, nurse name)
  const filteredRooms = rooms.filter((room) => {
    if (!searchQuery) return true
    const q = searchQuery.toLowerCase()
    const matchRoomNo = room.room_number ? room.room_number.toLowerCase().includes(q) : false
    const matchRoomName = room.room_name ? room.room_name.toLowerCase().includes(q) : false
    const matchPatient = room.patient?.name ? room.patient.name.toLowerCase().includes(q) : false
    const matchPatientId = room.patient_id ? String(room.patient_id).includes(q) : false
    const matchNurse = room.nurses ? room.nurses.some((n) => n.name ? n.name.toLowerCase().includes(q) : false) : false
    return matchRoomNo || matchRoomName || matchPatient || matchPatientId || matchNurse
  })

  // Clear all filters
  const handleResetFilters = () => {
    setSearchQuery('')
    setSelectedService('')
    setSelectedNurse('')
    setSelectedStatus('')
    setSelectedFloor('')
    setSortBy('room_number')
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Station Title */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="font-heading font-bold text-2xl text-navy-900 flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-teal-500 animate-ping shrink-0" />
            Ward Central Monitoring Station
          </h1>
          <p className="text-navy-400 text-sm">
            {user?.role === 'nurse'
              ? `Displaying assigned rooms for Nurse ${user.name}`
              : 'Aggregated real-time patient bed monitoring and sensor feeds.'}
          </p>
        </div>

        {/* Quick Reset */}
        <Button variant="ghost" size="sm" onClick={handleResetFilters} className="text-navy-500 hover:text-navy-800">
          <RefreshCw size={14} className="mr-1" /> Reset Central Filters
        </Button>
      </div>

      {/* Control Panel: Search & Filters */}
      <div className="bg-white border border-navy-100 rounded-2xl p-4 grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {/* Search */}
        <div className="relative md:col-span-2">
          <Search size={16} className="absolute left-3 top-3.5 text-navy-400" />
          <input
            type="text"
            placeholder="Search room, patient, nurse..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2.5 bg-navy-50/50 hover:bg-navy-50 border border-navy-100 focus:border-teal-500 rounded-xl text-sm focus:outline-none focus:ring-1 focus:ring-teal-500"
          />
        </div>

        {/* Service */}
        <div className="relative">
          <Filter size={12} className="absolute left-2.5 top-3.5 text-navy-400" />
          <select
            value={selectedService}
            onChange={(e) => setSelectedService(e.target.value)}
            className="w-full pl-7 pr-3 py-2.5 bg-navy-50/50 border border-navy-100 rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-teal-500"
          >
            <option value="">All Services</option>
            <option value="ecg">ECG</option>
            <option value="seizure">Seizure</option>
            <option value="fall">Fall</option>
          </select>
        </div>

        {/* Nurse (Admin/Doctor only) */}
        {user?.role !== 'nurse' ? (
          <div className="relative">
            <User size={12} className="absolute left-2.5 top-3.5 text-navy-400" />
            <select
              value={selectedNurse}
              onChange={(e) => setSelectedNurse(e.target.value)}
              className="w-full pl-7 pr-3 py-2.5 bg-navy-50/50 border border-navy-100 rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-teal-500"
            >
              <option value="">All Nurses</option>
              {nursesList.map(n => (
                <option key={n.id} value={n.id}>{n.name}</option>
              ))}
            </select>
          </div>
        ) : (
          <div className="bg-navy-50 border border-navy-100 text-navy-500 px-3 py-2.5 rounded-xl text-xs font-semibold flex items-center justify-center">
            My Rooms Scoped
          </div>
        )}

        {/* Status */}
        <div className="relative">
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
            className="w-full px-3 py-2.5 bg-navy-50/50 border border-navy-100 rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-teal-500"
          >
            <option value="">All Statuses</option>
            <option value="Monitoring">Monitoring</option>
            <option value="Warning">Warning</option>
            <option value="Critical Alert">Critical Alert</option>
            <option value="Initializing">Initializing</option>
            <option value="Idle">Idle</option>
            <option value="Offline">Offline</option>
          </select>
        </div>

        {/* Sorting */}
        <div className="relative">
          <SortAsc size={12} className="absolute left-2.5 top-3.5 text-navy-400" />
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="w-full pl-7 pr-3 py-2.5 bg-navy-50/50 border border-navy-100 rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-teal-500"
          >
            <option value="room_number">Room Number</option>
            <option value="patient_name">Patient Name</option>
            <option value="alert_priority">Alert Priority</option>
            <option value="highest_risk">Highest Risk</option>
          </select>
        </div>
      </div>

      {/* Main Grid */}
      {filteredRooms.length === 0 ? (
        <Card className="py-16 text-center border border-navy-100">
          <AlertCircle size={40} className="mx-auto mb-3 text-navy-300" />
          <p className="text-navy-500 font-semibold text-lg">No active rooms found</p>
          <p className="text-navy-400 text-sm mt-1">Try relaxing search terms or check room persistence config.</p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {filteredRooms.map((room) => (
            <RoomCard
              key={room.id}
              room={room}
              onViewDetails={() => navigate(`/${user.role}/rooms/${room.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * High-fidelity room display card.
 */
function RoomCard({ room, onViewDetails }) {
  const hasCritical = room.monitoring_status === 'Critical Alert'
  const hasWarning = room.monitoring_status === 'Warning'

  // Map service names to icons
  const renderServiceIcon = (svc) => {
    const s = svc.toLowerCase()
    const iconClass = "w-4 h-4"
    if (s === 'ecg') return <Heart key={s} className={`${iconClass} text-red-500`} title="ECG Monitoring" />
    if (s === 'seizure') return <Brain key={s} className={`${iconClass} text-purple-500`} title="Seizure Detection" />
    if (s === 'fall') return <AlertTriangle key={s} className={`${iconClass} text-amber-500`} title="Fall Detection" />
    return null
  }

  return (
    <div
      onClick={onViewDetails}
      className={`rounded-2xl border-2 p-5 bg-white transition-all duration-300 cursor-pointer flex flex-col justify-between h-[230px] group ${
        hasCritical
          ? 'border-red-500 shadow-lg shadow-red-50 hover:shadow-red-100 animate-pulse-slow'
          : hasWarning
          ? 'border-amber-400 shadow-md shadow-amber-50'
          : 'border-navy-100 hover:border-teal-400 hover:shadow-lg'
      }`}
    >
      {/* Header Info */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div>
            <span className="text-[10px] text-navy-400 font-bold uppercase tracking-widest block">Room</span>
            <span className="font-heading font-black text-xl text-navy-900 group-hover:text-teal-600 transition-colors">
              {room.room_number}
            </span>
            <span className="text-[10px] text-navy-400 font-medium ml-2 uppercase">Floor {room.floor || '1'}</span>
          </div>

          {/* Dynamic Status Badge */}
          <StatusBadge status={room.monitoring_status} />
        </div>

        {/* Patient Block */}
        <div className="space-y-1">
          {room.patient ? (
            <div>
              <p className="text-sm font-semibold text-navy-800">{room.patient.name}</p>
              <p className="text-xs text-navy-400 font-mono">Patient ID: {room.patient.id}</p>
            </div>
          ) : (
            <p className="text-xs italic text-navy-400 py-1">No patient assigned</p>
          )}
        </div>
      </div>

      {/* Alarms and Detections Block */}
      <div className="my-2 flex-1 flex flex-col justify-center">
        {room.active_alerts && room.active_alerts.length > 0 ? (
          <div className="space-y-1">
            {room.active_alerts.map((alt) => (
              <div
                key={alt.id}
                className="px-2.5 py-1 rounded-lg bg-red-50 border border-red-200 text-red-700 text-[10px] font-bold uppercase flex items-center justify-between"
              >
                <span>⚠ {alt.alert_type} Alarm</span>
                <span className="font-mono text-[9px]">{alt.severity}</span>
              </div>
            ))}
          </div>
        ) : room.patient ? (
          <div className="flex items-center gap-1.5 text-green-700 text-[11px] font-medium bg-green-50 rounded-lg px-2.5 py-1.5 w-fit">
            <CheckCircle2 size={13} /> Signals Stable
          </div>
        ) : null}
      </div>

      {/* Footer Info: Services, Nurses, and View Button */}
      <div className="border-t border-navy-50 pt-3 flex items-center justify-between text-xs">
        {/* Service Icons */}
        <div className="flex items-center gap-1.5">
          {room.services.map(renderServiceIcon)}
        </div>

        {/* Assigned Nurse(s) */}
        <div className="text-right">
          {room.nurses.length > 0 ? (
            <p className="text-[10px] text-navy-400 font-medium truncate max-w-[120px]">
              Nurse: {room.nurses.map(n => {
                const parts = n.name.split(' ')
                return parts[0].toLowerCase() === 'nurse' && parts.length > 1 ? parts[1] : parts[0]
              }).join(', ')}
            </p>
          ) : (
            <p className="text-[10px] text-navy-300 italic">Unassigned</p>
          )}
        </div>

        {/* Hover View Button */}
        <div className="hidden group-hover:block transition-all pl-2">
          <span className="flex items-center gap-0.5 text-xs text-teal-600 font-bold">
            <Eye size={12} /> Monitor
          </span>
        </div>
      </div>
    </div>
  )
}
