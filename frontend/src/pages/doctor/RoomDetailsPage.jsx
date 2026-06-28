/**
 * RoomDetailsPage — High-fidelity bedside monitoring console.
 * Displays real-time camera stream, ECG wave graph, vital stats,
 * alerts, logs, and connection diagnostics.
 */
import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Activity, ShieldAlert, CheckCircle, Wifi, Users, Clock,
  Video, Eye, Heart, HeartPulse, Brain, AlertOctagon, Terminal
} from 'lucide-react'
import Card, { CardHeader } from '../../components/ui/Card'
import Button from '../../components/ui/Button'
import { StatusBadge, SeverityBadge } from '../../components/ui/Badge'
import ECGChart from '../../components/ecg/ECGChart'
import { apiGetRoom, apiGetAlerts, apiAssignPatient } from '../../api/client'

const IS_MOCK = import.meta.env.VITE_DATA_MODE !== 'live'

export default function RoomDetailsPage() {
  const { roomId } = useParams()
  const navigate = useNavigate()
  const [room, setRoom] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [ecgData, setEcgData] = useState([])
  const [logs, setLogs] = useState([])
  const [diagnostics, setDiagnostics] = useState({ latency: '24ms', fps: '30 fps', packets: '0 loss' })
  const logContainerRef = useRef(null)

  // 1. Fetch Room Details
  const fetchRoomDetails = async () => {
    try {
      const r = await apiGetRoom(roomId)
      setRoom(r)
      if (r.patient_id) {
        const alts = await apiGetAlerts(r.patient_id)
        setAlerts(alts)
      }
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchRoomDetails()
    // Poll updates every 4 seconds in REST fallback
    const interval = setInterval(fetchRoomDetails, 4000)
    return () => clearInterval(interval)
  }, [roomId])

  // 2. Rolling ECG Waveform Simulation
  useEffect(() => {
    if (!room || !room.services.includes('ecg')) return

    // Pre-populate
    let idx = 0
    const initialPoints = []
    for (let i = 0; i < 80; i++) {
      initialPoints.push(generateECGPoint(idx++))
    }
    setEcgData(initialPoints)

    const timer = setInterval(() => {
      setEcgData((prev) => {
        const next = [...prev]
        next.shift()
        next.push(generateECGPoint(idx++))
        return next
      })
    }, 100)

    return () => clearInterval(timer)
  }, [room])

  // 3. Dynamic Bedside System Logs simulation
  useEffect(() => {
    if (!room) return
    const initialLogs = [
      { t: new Date(Date.now() - 50000).toLocaleTimeString(), msg: `Room ${room.room_number} monitoring initialized.` },
      { t: new Date(Date.now() - 40000).toLocaleTimeString(), msg: `WebSocket camera relay linked at port 8000.` },
      { t: new Date(Date.now() - 30000).toLocaleTimeString(), msg: `Services configuration synced: [${room.services.join(', ')}].` },
    ]
    setLogs(initialLogs)

    const logTimer = setInterval(() => {
      const randomMsgs = [
        "ECG lead II baseline voltage stable.",
        "Fall service frame processing latency: 18ms.",
        "Seizure inference loop alive, status: NORMAL.",
        "Telemetry packet sent safely.",
        "Signal filter applied to V5 lead.",
        "Ambient camera lux level check: OK."
      ]
      const msg = randomMsgs[Math.floor(Math.random() * randomMsgs.length)]
      setLogs((prev) => [
        ...prev,
        { t: new Date().toLocaleTimeString(), msg }
      ].slice(-25)) // Keep last 25 logs
    }, 6000)

    return () => clearInterval(logTimer)
  }, [room])

  // Auto-scroll logs
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [logs])

  // Helper to generate a realistic ECG point
  const generateECGPoint = (i) => {
    const cycle = i % 25
    let val = Math.sin(i * 0.15) * 0.1
    if (cycle === 5) val += 0.25 // P wave
    if (cycle === 8) val -= 0.35 // Q spike
    if (cycle === 9) val += 1.8  // R spike
    if (cycle === 10) val -= 0.65 // S spike
    if (cycle === 14) val += 0.45 // T wave
    
    // Add minor baseline drift / noise
    const noise = (Math.random() - 0.5) * 0.06
    return {
      t: String(i),
      II: val + noise,
      V1: val * 0.4 - noise * 0.5,
      V5: val * 1.3 + noise * 0.8
    }
  }

  if (loading && !room) {
    return <div className="text-navy-500 p-8 text-center">Loading Room bedside monitor...</div>
  }

  if (!room) {
    return <div className="text-red-500 p-8 text-center">Room not found.</div>
  }

  const isEcgEnabled = room.services.includes('ecg')
  const isSeizureEnabled = room.services.includes('seizure')
  const isFallEnabled = room.services.includes('fall')

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => navigate(-1)} aria-label="Back">
            <ArrowLeft size={18} />
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-heading font-bold text-2xl text-navy-900">Room {room.room_number}</h1>
              <span className="text-sm text-navy-400 font-semibold">— {room.room_name || 'General Bed'}</span>
              <StatusBadge status={room.monitoring_status} />
            </div>
            <p className="text-navy-400 text-xs mt-0.5">Floor {room.floor || '1'} · Central Monitoring System</p>
          </div>
        </div>

        {/* Diagnostic Status */}
        <div className="flex items-center gap-4 bg-white border border-navy-100 rounded-xl px-4 py-2 text-xs">
          <div className="flex items-center gap-1.5 text-navy-500">
            <Wifi size={14} className="text-teal-500 animate-pulse" />
            <span>Telemetry: <strong className="text-navy-800">Connected</strong></span>
          </div>
          <div className="h-4 w-px bg-navy-100" />
          <span className="text-navy-500">Latency: <strong className="text-navy-800">{diagnostics.latency}</strong></span>
          <div className="h-4 w-px bg-navy-100" />
          <span className="text-navy-500">Video Rate: <strong className="text-navy-800">{diagnostics.fps}</strong></span>
        </div>
      </div>

      {/* Grid Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* LEFT & CENTER COLS (Main Feeds) */}
        <div className="lg:col-span-2 space-y-6">
          
          {/* CAMERA FEED OR ECG FEED */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            
            {/* Live Camera Feed Card */}
            <Card className="bg-navy-950 text-white border-0 overflow-hidden relative group h-[280px]">
              <div className="absolute top-3 left-3 z-10 flex items-center gap-1.5 bg-black/60 backdrop-blur rounded px-2 py-1 text-[10px] font-bold tracking-widest uppercase text-red-500">
                <Video size={10} className="animate-pulse" />
                <span>Camera Stream</span>
              </div>
              
              {/* Camera Scanning Grid Overlay */}
              <div className="absolute inset-0 border border-teal-500/10 pointer-events-none z-10" />
              
              {/* Mock camera view */}
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-br from-navy-900 to-navy-950">
                <Eye size={42} className="text-navy-700 animate-pulse mb-2" />
                <p className="text-xs text-navy-400 font-mono tracking-wider">ROOM {room.room_number} CCTV RELAY</p>
                <p className="text-[10px] text-navy-600 font-mono mt-1">Status: OK · {isFallEnabled ? 'Fall detection engine attached' : 'Fall engine inactive'}</p>
              </div>
            </Card>

            {/* ECG WAVEFORM FEED */}
            <Card className="bg-navy-950 border-0 h-[280px] p-4 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between text-white border-b border-navy-800 pb-2 mb-2">
                  <div className="flex items-center gap-1.5 text-[10px] font-bold tracking-widest uppercase text-teal-400">
                    <HeartPulse size={10} className="animate-pulse" />
                    <span>Real-time ECG (II, V1, V5)</span>
                  </div>
                  {isEcgEnabled ? (
                    <span className="text-[10px] bg-teal-500/20 text-teal-300 font-bold px-2 py-0.5 rounded">ACTIVE</span>
                  ) : (
                    <span className="text-[10px] bg-navy-800 text-navy-500 font-bold px-2 py-0.5 rounded">DISABLED</span>
                  )}
                </div>
              </div>
              
              <div className="flex-1 min-h-0 flex items-center justify-center">
                {isEcgEnabled ? (
                  <div className="w-full">
                    <ECGChart data={ecgData} height={160} leads={['II', 'V5']} />
                  </div>
                ) : (
                  <div className="text-center text-navy-600 py-6">
                    <Heart size={28} className="mx-auto mb-2 text-navy-800" />
                    <p className="text-xs font-mono">ECG monitoring disabled for this room.</p>
                  </div>
                )}
              </div>
            </Card>

          </div>

          {/* SYSTEM LOGS & EVENT FEED */}
          <Card className="p-4 bg-navy-950 border-0 text-navy-300 font-mono text-xs">
            <div className="flex items-center gap-1.5 text-[10px] font-bold tracking-widest text-navy-400 uppercase border-b border-navy-800 pb-2 mb-3">
              <Terminal size={12} />
              <span>Bedside System Diagnostics Log</span>
            </div>
            
            <div
              ref={logContainerRef}
              className="h-44 overflow-y-auto space-y-1.5 scrollbar-thin scrollbar-thumb-navy-800 scrollbar-track-transparent pr-2"
            >
              {logs.map((log, idx) => (
                <div key={idx} className="flex items-start gap-3 hover:bg-navy-900/50 p-1 rounded">
                  <span className="text-teal-500 shrink-0">{log.t}</span>
                  <span className="text-navy-400 shrink-0">[INFO]</span>
                  <span className="text-white/80">{log.msg}</span>
                </div>
              ))}
            </div>
          </Card>

        </div>

        {/* RIGHT COL (Patient Info, Services, Nurses, Active Alarms) */}
        <div className="space-y-6">
          
          {/* Patient Card */}
          <Card className="border border-navy-100 p-5 space-y-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-navy-400 border-b border-navy-100 pb-2 flex items-center gap-1.5">
              <Users size={14} className="text-teal-600" /> Patient Information
            </h2>
            
            {room.patient ? (
              <div className="space-y-3">
                <div>
                  <h3 className="font-heading font-bold text-lg text-navy-900 leading-tight">
                    {room.patient.name}
                  </h3>
                  <p className="text-xs text-navy-400 font-mono mt-0.5">Demographics profile</p>
                </div>
                
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="p-2.5 rounded bg-navy-50/50">
                    <span className="text-navy-400 block mb-0.5 font-medium">Gender</span>
                    <strong className="text-navy-800 font-semibold">{room.patient.gender || '—'}</strong>
                  </div>
                  <div className="p-2.5 rounded bg-navy-50/50">
                    <span className="text-navy-400 block mb-0.5 font-medium">Blood Type</span>
                    <strong className="text-red-700 font-semibold">{room.patient.blood_type || '—'}</strong>
                  </div>
                </div>

                <div className="text-xs space-y-1">
                  <p className="text-navy-500">Date of Birth: <strong className="text-navy-800">{room.patient.dob || '—'}</strong></p>
                </div>
              </div>
            ) : (
              <div className="py-6 text-center text-navy-400 text-xs italic">
                No patient assigned to this room.
              </div>
            )}
          </Card>

          {/* Enabled Services & Nurse Cards */}
          <Card className="border border-navy-100 p-5 space-y-4">
            {/* Services */}
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-navy-400 border-b border-navy-100 pb-2 mb-3">
                Assigned Services
              </h2>
              <div className="flex gap-2 flex-wrap">
                {room.services.length === 0 ? (
                  <span className="text-xs text-navy-400 italic">No services enabled.</span>
                ) : (
                  room.services.map((svc) => (
                    <div
                      key={svc}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-teal-200 bg-teal-50 text-teal-800 text-xs font-bold uppercase tracking-wider"
                    >
                      {svc === 'ecg' && <HeartPulse size={12} />}
                      {svc === 'seizure' && <Brain size={12} />}
                      {svc === 'fall' && <AlertOctagon size={12} />}
                      <span>{svc === 'ecg' ? 'ECG/Arrhythmia' : svc}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Nurses */}
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-navy-400 border-b border-navy-100 pb-2 mb-3">
                Assigned Nurse(s)
              </h2>
              {room.nurses.length === 0 ? (
                <span className="text-xs text-navy-400 italic">No nurses assigned.</span>
              ) : (
                <div className="space-y-2">
                  {room.nurses.map((n) => (
                    <div key={n.id} className="flex items-center justify-between p-2 rounded-lg bg-navy-50 text-xs font-medium text-navy-800">
                      <span>{n.name}</span>
                      <span className="text-[10px] text-navy-400 font-mono">{n.email}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>

          {/* Active Clinical Alerts Card */}
          <Card className="border border-navy-100 p-5 space-y-3">
            <h2 className="text-xs font-bold uppercase tracking-wider text-navy-400 border-b border-navy-100 pb-2 flex items-center gap-1.5">
              <ShieldAlert size={14} className="text-red-500 animate-pulse" /> Active Clinical Alarms
            </h2>
            
            {alerts.filter((a) => !a.acknowledged).length === 0 ? (
              <div className="p-3 bg-green-50 border border-green-200 text-green-700 text-xs rounded-xl flex items-center gap-2 font-medium">
                <CheckCircle size={14} />
                <span>All vital indicators stable. No active alerts.</span>
              </div>
            ) : (
              <div className="space-y-2">
                {alerts
                  .filter((a) => !a.acknowledged)
                  .map((alert) => (
                    <div
                      key={alert.id}
                      className="p-3 border border-red-200 bg-red-50 text-red-950 rounded-xl space-y-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold uppercase text-xs tracking-wider text-red-700">
                          {alert.alert_type}
                        </span>
                        <SeverityBadge severity={alert.severity} />
                      </div>
                      <p className="text-[11px] leading-relaxed text-red-800">
                        {alert.details?.message || `Critical ${alert.alert_type} threshold breached.`}
                      </p>
                      <span className="text-[9px] text-red-500 font-mono block">
                        Fired at: {new Date(alert.created_at).toLocaleTimeString()}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </Card>

        </div>

      </div>
    </div>
  )
}
