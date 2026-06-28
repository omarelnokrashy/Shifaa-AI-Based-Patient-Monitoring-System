import { useState, useEffect, useRef } from 'react'
import { Camera, Video, AlertTriangle, Play, Square, Upload, FileVideo, Loader2, Activity } from 'lucide-react'
import { http } from '../../api/client'
import useAuthStore from '../../store/authStore'
import useAlertsStore from '../../store/alertsStore'
import { LineChart, Line, YAxis, CartesianGrid, ResponsiveContainer } from 'recharts'

export default function SandboxTestPage() {
  const user = useAuthStore((s) => s.user)
  const isLive = import.meta.env.VITE_DATA_MODE === 'live'

  // Input configuration modes
  const [inputMode, setInputMode] = useState('webcam') // 'webcam' | 'video'
  const [selectedVideoFile, setSelectedVideoFile] = useState(null)
  const [localVideoUrl, setLocalVideoUrl] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const [uploadedFilePath, setUploadedFilePath] = useState('')
  const [backgroundUploadStatus, setBackgroundUploadStatus] = useState('') // '', 'uploading', 'ready', 'failed'

  // Options
  const [patients, setPatients] = useState([])
  const [selectedPatientId, setSelectedPatientId] = useState('')
  const [seizureSource, setSeizureSource] = useState('0') // '0' is webcam
  const [seizureMode, setSeizureMode] = useState('monitor')

  // Statuses
  const [isFallActive, setIsFallActive] = useState(false)
  const [isSeizureActive, setIsSeizureActive] = useState(false)
  const [fallStatus, setFallStatus] = useState('NORMAL') // NORMAL, FALL
  const [fallProb, setFallProb] = useState(0.0)
  const [seizureStatus, setSeizureStatus] = useState('INITIALISING') // INITIALISING, NORMAL, SEIZURE
  const [seizureSignal, setSeizureSignal] = useState(0.0)
  const [seizureRisk, setSeizureRisk] = useState(0.0)
  const [cjProb, setCjProb] = useState(0.0)
  const [seizureReady, setSeizureReady] = useState(false)

  // Latch statuses
  const [fallLatchActive, setFallLatchActive] = useState(false)
  const [fallLatchRemaining, setFallLatchRemaining] = useState(0.0)
  const mockLatchRef = useRef({ active: false, startTime: null, streak: 0 })

  const [seizureLatchActive, setSeizureLatchActive] = useState(false)
  const [seizureLatchRemaining, setSeizureLatchRemaining] = useState(0.0)
  const seizureLatchStartRef = useRef(null)

  // ECG specific states
  const [activeTab, setActiveTab] = useState('vision') // 'vision' | 'ecg'
  const [ecgRecords, setEcgRecords] = useState([])
  const [selectedRecord, setSelectedRecord] = useState('')
  const [ecgSignalData, setEcgSignalData] = useState([])
  const [ecgLeads, setEcgLeads] = useState([])
  const [selectedLeadIndex, setSelectedLeadIndex] = useState(1) // Lead II default
  const [isEcgStreaming, setIsEcgStreaming] = useState(false)
  const [ecgSampleIndex, setEcgSampleIndex] = useState(0)
  const [ecgResult, setEcgResult] = useState(null)
  const [isEcgAnalyzing, setIsEcgAnalyzing] = useState(false)
  
  // Console logs
  const [logs, setLogs] = useState([])

  // Webcams, video playing & loops
  const videoRef = useRef(null)
  const streamRef = useRef(null)
  const fallWsRef = useRef(null)
  const seizureWsRef = useRef(null)
  const intervalRef = useRef(null)
  const eventBufferRef = useRef([])
  const loggedSecsRef = useRef(new Set())
  const uploadedFilePathRef = useRef('')

  const handleTimeUpdate = () => {
    if (inputMode !== 'video' || !isSeizureActive) return
    if (!videoRef.current) return
    const currentTime = videoRef.current.currentTime

    // Find the event in buffer closest to (but not exceeding) currentTime
    const buffer = eventBufferRef.current
    let matchingEvent = null
    for (let i = 0; i < buffer.length; i++) {
      if (buffer[i].time_sec <= currentTime) {
        matchingEvent = buffer[i]
      } else {
        break
      }
    }

    if (matchingEvent) {
      const prevStatus = seizureStatus
      const newStatus = matchingEvent.status || 'NORMAL'
      setSeizureStatus(newStatus)
      setSeizureSignal(matchingEvent.gate_score || 0.0)
      setSeizureRisk(matchingEvent.current_risk || 0.0)
      setCjProb(matchingEvent.cj_prob || 0.0)

      if (newStatus === 'SEIZURE') {
        const secKey = Math.floor(matchingEvent.time_sec)
        if (!loggedSecsRef.current.has(secKey)) {
          loggedSecsRef.current.add(secKey)
          addLog('Seizure Svc', `⚠️ Seizure active! Signal: ${matchingEvent.gate_score?.toFixed(3)}`, 'danger')
        }

        if (prevStatus !== 'SEIZURE') {
          useAlertsStore.getState().playAlarmSound()
          setSeizureLatchActive(true)
          setSeizureLatchRemaining(30.0)
          seizureLatchStartRef.current = Date.now()
          if (isLive) {
            http.post('/api/monitoring/seizure/trigger-alert', {
              patient_id: Number(selectedPatientId),
              details: matchingEvent
            }).catch(err => {
              console.error("Failed to trigger playhead seizure alert:", err)
            })
          }
        }
      } else {
        if (prevStatus === 'SEIZURE') {
          setSeizureLatchActive(false)
          setSeizureLatchRemaining(0.0)
          seizureLatchStartRef.current = null
        }
      }
    }
  }

  // Fetch patients on load
  useEffect(() => {
    const loadPatients = async () => {
      try {
        if (isLive) {
          const { data } = await http.get('/api/patients')
          setPatients(data)
          if (data.length > 0) setSelectedPatientId(String(data[0].id))
        } else {
          // Mock patients
          const mockList = [
            { id: 7223, name: 'Anthony Blanchard' },
            { id: 1021, name: 'Jane Doe' },
          ]
          setPatients(mockList)
          setSelectedPatientId('7223')
        }
      } catch (err) {
        addLog('System', `Failed to load patients: ${err.message}`, 'danger')
      }
    }
    loadPatients()
  }, [isLive])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopFallTest()
      stopSeizureTest()
      stopWebcam()
      if (typeof stopEcgStream === 'function') {
        stopEcgStream()
      }
      if (localVideoUrl) {
        URL.revokeObjectURL(localVideoUrl)
      }
    }
  }, [localVideoUrl])

  // Seizure Latch Countdown Effect
  useEffect(() => {
    if (!seizureLatchActive) return
    const id = setInterval(() => {
      if (seizureLatchStartRef.current) {
        const elapsed = (Date.now() - seizureLatchStartRef.current) / 1000
        const remaining = Math.max(0, 30.0 - elapsed)
        setSeizureLatchRemaining(remaining)
        if (remaining <= 0) {
          setSeizureLatchActive(false)
          setSeizureLatchRemaining(0.0)
        }
      }
    }, 200)
    return () => clearInterval(id)
  }, [seizureLatchActive])

  // Reactive Alarm Playback Manager Effect
  useEffect(() => {
    const shouldAlarmPlay =
      (isFallActive && (fallStatus === 'FALL' || fallLatchActive)) ||
      (isSeizureActive && (seizureStatus === 'SEIZURE' || seizureLatchActive))

    if (shouldAlarmPlay) {
      const currentAudio = useAlertsStore.getState().currentAudio
      if (!currentAudio) {
        useAlertsStore.getState().playAlarmSound()
      }
    } else {
      const currentAudio = useAlertsStore.getState().currentAudio
      if (currentAudio) {
        useAlertsStore.getState().stopAlarmSound()
      }
    }
  }, [isFallActive, fallStatus, fallLatchActive, isSeizureActive, seizureStatus, seizureLatchActive])

  const addLog = (service, message, type = 'info') => {
    setLogs((prev) => [
      {
        id: Date.now() + Math.random(),
        time: new Date().toLocaleTimeString(),
        service,
        message,
        type,
      },
      ...prev.slice(0, 49),
    ])
  }

  // ── Video File Loading ──────────────────────────────────────────────────────
  const handleVideoSelect = async (e) => {
    const file = e.target.files[0]
    if (!file) return

    // Stop current runs before loading new file
    stopFallTest()
    stopSeizureTest()
    stopWebcam()

    if (localVideoUrl) {
      URL.revokeObjectURL(localVideoUrl)
    }

    setSelectedVideoFile(file)
    setUploadedFilePath('')
    uploadedFilePathRef.current = ''
    setBackgroundUploadStatus('')
    const url = URL.createObjectURL(file)
    setLocalVideoUrl(url)

    if (videoRef.current) {
      videoRef.current.srcObject = null
      videoRef.current.muted = true
      videoRef.current.src = url
      videoRef.current.load()
    }
    addLog('Video', `Loaded file: ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`, 'success')

    if (isLive) {
      setBackgroundUploadStatus('uploading')
      addLog('Seizure Svc', 'Uploading video to server workspace in background...', 'info')
      const formData = new FormData()
      formData.append('file', file)
      try {
        const uploadRes = await http.post('/api/monitoring/seizure/upload-test-video', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        setUploadedFilePath(uploadRes.data.file_path)
        uploadedFilePathRef.current = uploadRes.data.file_path
        setBackgroundUploadStatus('ready')
        addLog('Seizure Svc', 'Video uploaded successfully to server workspace.', 'success')
      } catch (err) {
        setBackgroundUploadStatus('failed')
        addLog('Seizure Svc', `Background video upload failed: ${err.message}`, 'danger')
      }
    } else {
      setBackgroundUploadStatus('ready')
    }
  }

  // ── Webcam Utilities ────────────────────────────────────────────────────────
  const startWebcam = async () => {
    if (streamRef.current) return true
    try {
      addLog('Camera', 'Requesting webcam access...', 'info')
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, frameRate: 15 },
      })
      if (videoRef.current) {
        videoRef.current.src = ''
        videoRef.current.srcObject = stream
        videoRef.current.play().catch(err => console.warn("Webcam play blocked:", err))
      }
      streamRef.current = stream
      addLog('Camera', 'Webcam started successfully.', 'success')
      return true
    } catch (err) {
      addLog('Camera', `Failed to access webcam: ${err.message}`, 'danger')
      return false
    }
  }

  const stopWebcam = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
  }

  // ── Fall Detection Test ──────────────────────────────────────────────────────
  const startFallTest = async () => {
    if (isFallActive) return
    if (!selectedPatientId) {
      addLog('Fall Svc', 'Please select a patient first.', 'warning')
      return
    }
    
    if (inputMode === 'webcam') {
      const cameraReady = await startWebcam()
      if (!cameraReady) return
    } else {
      if (!selectedVideoFile) {
        addLog('Fall Svc', 'Please upload/select a video file first.', 'warning')
        return
      }
      if (videoRef.current) {
        videoRef.current.muted = true
        videoRef.current.play().catch((err) => {
          console.warn("Fall test video play blocked:", err)
        })
      }
    }

    setIsFallActive(true)
    addLog('Fall Svc', `Starting fall detection stream using ${inputMode}...`, 'info')

    if (!isLive) {
      // Mock simulation loop
      addLog('Fall Svc', '[MOCK] Connected to mock fall stream.', 'success')
      let ticks = 0
      mockLatchRef.current = { active: false, startTime: null, streak: 0 }
      
      intervalRef.current = setInterval(() => {
        ticks++
        const now = Date.now()
        const state = mockLatchRef.current

        if (state.active) {
          const elapsed = (now - state.startTime) / 1000
          if (elapsed >= 30.0) {
            state.active = false
            state.startTime = null
            state.streak = 0
            setFallStatus('NORMAL')
            setFallProb(0.0)
            setFallLatchActive(false)
            setFallLatchRemaining(0.0)
          } else {
            setFallStatus('FALL')
            setFallLatchActive(true)
            setFallLatchRemaining(30.0 - elapsed)
          }
        }

        if (!state.active) {
          const mockProb = Math.min(1.0, Math.max(0.0, 0.1 + Math.sin(ticks / 5) * 0.15 + (Math.random() * 0.05)))
          setFallProb(mockProb)

          if (mockProb > 0.85) {
            state.streak += 1
          } else {
            state.streak = 0
          }

          const alarmActive = state.streak >= 2
          setFallStatus(alarmActive ? 'FALL' : 'NORMAL')

          if (alarmActive) {
            state.active = true
            state.startTime = now
            setFallLatchActive(true)
            setFallLatchRemaining(30.0)
            addLog('Fall Svc', `⚠️ [MOCK] Anomaly alert generated with probability: ${(mockProb * 100).toFixed(1)}%`, 'danger')
            useAlertsStore.getState().playAlarmSound()
          }
        }
      }, 300)
      return
    }

    try {
      // 1. Create a session on backend
      const res = await http.post('/api/monitoring/fall/start', {
        room_id: `sandbox_${selectedPatientId}`,
        patient_id: Number(selectedPatientId),
      })
      addLog('Fall Svc', `Session created. Connecting bridge: ${res.data.ws_url}`, 'info')

      // 2. Connect WebSocket
      const wsUrl = `ws://${window.location.host}${res.data.ws_url}`
      const ws = new WebSocket(wsUrl)
      fallWsRef.current = ws

      ws.onopen = () => {
        addLog('Fall Svc', 'WebSocket bridge connected. Streaming frames...', 'success')
        
        // Setup frame sender loop - use 640x480 for better MediaPipe Pose accuracy
        const canvas = document.createElement('canvas')
        canvas.width = 640
        canvas.height = 480
        const ctx = canvas.getContext('2d')

        intervalRef.current = setInterval(() => {
          if (videoRef.current && (videoRef.current.readyState === 4 || videoRef.current.readyState === 3 || videoRef.current.readyState === 2)) {
            ctx.drawImage(videoRef.current, 0, 0, 640, 480)
            canvas.toBlob((blob) => {
              if (blob && ws.readyState === WebSocket.OPEN) {
                blob.arrayBuffer().then((buf) => {
                  ws.send(buf)
                })
              }
            }, 'image/jpeg', 0.6)
          }
        }, 100) // ~10 FPS
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.fall_detected !== undefined) {
            setFallStatus(data.fall_detected ? 'FALL' : 'NORMAL')
            setFallProb(data.fall_probability || 0.0)
            setFallLatchActive(data.latch_active || false)
            setFallLatchRemaining(data.latch_remaining || 0.0)
            if (data.fall_detected) {
              addLog('Fall Svc', `⚠️ Fall detected! Prob: ${(data.fall_probability * 100).toFixed(1)}%`, 'danger')
            }
          }
        } catch (err) {
          console.error(err)
        }
      }

      ws.onerror = (err) => {
        addLog('Fall Svc', `WebSocket connection error: ${err.message || 'Unknown'}`, 'danger')
      }

      ws.onclose = () => {
        addLog('Fall Svc', 'WebSocket bridge closed.', 'info')
        setIsFallActive(false)
      }

    } catch (err) {
      addLog('Fall Svc', `Failed to start fall test: ${err.message}`, 'danger')
      setIsFallActive(false)
    }
  }

  const stopFallTest = async () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    if (fallWsRef.current) {
      fallWsRef.current.close()
      fallWsRef.current = null
    }
    setIsFallActive(false)
    setFallStatus('NORMAL')
    setFallProb(0.0)
    setFallLatchActive(false)
    setFallLatchRemaining(0.0)
    useAlertsStore.getState().stopAlarmSound()
    addLog('Fall Svc', 'Fall detection test stopped.', 'info')

    if (inputMode === 'video' && videoRef.current) {
      videoRef.current.pause()
    }

    if (isLive && selectedPatientId) {
      try {
        await http.delete(`/api/monitoring/fall/sandbox_${selectedPatientId}/stop`)
      } catch (err) {
        console.warn('Failed to delete fall session:', err.message)
      }
    }
    if (!isSeizureActive) stopWebcam()
  }

  // ── Seizure Detection Test ──────────────────────────────────────────────────
  const startSeizureTest = async () => {
    if (isSeizureActive) return
    if (!selectedPatientId) {
      addLog('Seizure Svc', 'Please select a patient first.', 'warning')
      return
    }

    setIsSeizureActive(true)

    if (!isLive) {
      if (inputMode === 'video') {
        if (!selectedVideoFile) {
          addLog('Seizure Svc', 'Please upload a video file first.', 'warning')
          setIsSeizureActive(false)
          return
        }
        if (videoRef.current) {
          videoRef.current.muted = true
          videoRef.current.pause()
          videoRef.current.currentTime = 0
        }
      }

      // Mock simulation loop
      addLog('Seizure Svc', '[MOCK] Connected to mock seizure WS.', 'success')
      let ticks = 0
      setSeizureStatus('INITIALISING')
      setSeizureReady(false)
      eventBufferRef.current = []
      loggedSecsRef.current.clear()

      intervalRef.current = setInterval(() => {
        ticks++
        if (ticks < 10) {
          setSeizureStatus('INITIALISING')
          return
        }
        setSeizureReady(true)
        if (inputMode === 'video' && videoRef.current && videoRef.current.paused) {
          videoRef.current.muted = true
          videoRef.current.play().catch((err) => {
            console.warn("Mock play blocked:", err)
          })
          addLog('Seizure Svc', '[MOCK] Pipeline ready. Starting video playback...', 'success')
        }
        const mockSig = Math.min(1.0, Math.max(0.0, 0.05 + Math.sin(ticks / 7) * 0.1 + (Math.random() * 0.03)))

        if (inputMode === 'video') {
          // Push a simulated event
          const simulatedEvent = {
            ready: true,
            status: mockSig > 0.8 ? 'SEIZURE' : 'NORMAL',
            gate_score: mockSig,
            current_risk: mockSig * 1.2,
            cj_prob: mockSig * 0.8,
            time_sec: (ticks - 10) * 0.5, // matches tick timing
          }
          eventBufferRef.current.push(simulatedEvent)
        } else {
          setSeizureSignal(mockSig)
          setSeizureRisk(mockSig * 1.2)
          setCjProb(mockSig * 0.8)
          const prevStatus = seizureStatus
          const newStatus = mockSig > 0.8 ? 'SEIZURE' : 'NORMAL'
          setSeizureStatus(newStatus)
          if (newStatus === 'SEIZURE') {
            if (prevStatus !== 'SEIZURE') {
              addLog('Seizure Svc', `⚠️ [MOCK] Seizure activity signature detected!`, 'danger')
              setSeizureLatchActive(true)
              setSeizureLatchRemaining(30.0)
              seizureLatchStartRef.current = Date.now()
              useAlertsStore.getState().playAlarmSound()
            }
          } else {
            if (prevStatus === 'SEIZURE') {
              setSeizureLatchActive(false)
              setSeizureLatchRemaining(0.0)
              seizureLatchStartRef.current = null
            }
          }
        }
      }, 500)
      return
    }

    try {
      let finalSource = seizureSource

      // If we are in video mode, we must ensure the video file is uploaded
      if (inputMode === 'video') {
        if (!selectedVideoFile) {
          addLog('Seizure Svc', 'Please select a video file first.', 'warning')
          setIsSeizureActive(false)
          return
        }

        let sourcePath = uploadedFilePathRef.current

        if (!sourcePath) {
          if (backgroundUploadStatus === 'uploading') {
            addLog('Seizure Svc', 'Waiting for background video upload to complete...', 'info')
            setIsUploading(true)
            let retries = 120
            while (!uploadedFilePathRef.current && retries > 0) {
              await new Promise((resolve) => setTimeout(resolve, 500))
              retries--
            }
            setIsUploading(false)
            sourcePath = uploadedFilePathRef.current
          }

          if (!sourcePath) {
            setIsUploading(true)
            addLog('Seizure Svc', 'Uploading video to server workspace (synchronous fallback)...', 'info')
            const formData = new FormData()
            formData.append('file', selectedVideoFile)
            try {
              const uploadRes = await http.post('/api/monitoring/seizure/upload-test-video', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
              })
              sourcePath = uploadRes.data.file_path
              setUploadedFilePath(sourcePath)
              uploadedFilePathRef.current = sourcePath
              setBackgroundUploadStatus('ready')
              addLog('Seizure Svc', 'Video uploaded successfully.', 'success')
            } catch (err) {
              addLog('Seizure Svc', `Video upload failed: ${err.message}`, 'danger')
              setIsSeizureActive(false)
              setIsUploading(false)
              return
            }
            setIsUploading(false)
          }
        }

        finalSource = sourcePath
        // Start paused, reset playhead
        if (videoRef.current) {
          videoRef.current.muted = true
          videoRef.current.pause()
          videoRef.current.currentTime = 0
        }
      }

      // Initialize state for the new session
      setSeizureReady(false)
      eventBufferRef.current = []
      loggedSecsRef.current.clear()

      addLog('Seizure Svc', `Starting subprocess session for Patient ${selectedPatientId}...`, 'info')

      // 1. POST to start session
      const res = await http.post('/api/monitoring/seizure/start', {
        patient_id: Number(selectedPatientId),
        source: finalSource,
        mode: seizureMode,
      })
      addLog('Seizure Svc', `Subprocess spawned with source: ${finalSource}. Status: ${res.data.alive ? 'ALIVE' : 'FAILED'}`, 'info')

      // 2. Connect directly to Seizure service websocket on port 8003
      const wsUrl = `ws://${window.location.hostname}:8003/ws/${selectedPatientId}`
      addLog('Seizure Svc', `Subscribing to WS: ${wsUrl}`, 'info')
      const ws = new WebSocket(wsUrl)
      seizureWsRef.current = ws

      ws.onopen = () => {
        addLog('Seizure Svc', 'WebSocket connected. Awaiting signals...', 'success')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          
          if (inputMode === 'video') {
            eventBufferRef.current.push(data)
            
            if (data.ready) {
              setSeizureReady(true)
              if (videoRef.current) {
                videoRef.current.muted = true
                if (videoRef.current.paused) {
                  videoRef.current.play().catch(err => {
                    console.warn("Seizure test video play blocked:", err)
                  })
                  addLog('Seizure Svc', 'Pipeline ready. Starting video playback...', 'success')
                }
              }
            } else {
              setSeizureStatus('INITIALISING')
            }
          } else {
            // Live webcam
            setSeizureReady(true)
            const prevStatus = seizureStatus
            const newStatus = data.status || 'INITIALISING'
            setSeizureStatus(newStatus)
            setSeizureSignal(data.gate_score || 0.0)
            setSeizureRisk(data.current_risk || 0.0)
            setCjProb(data.cj_prob || 0.0)
            
            if (newStatus === 'SEIZURE') {
              if (prevStatus !== 'SEIZURE') {
                addLog('Seizure Svc', `⚠️ Seizure active! Signal: ${data.gate_score?.toFixed(3)}`, 'danger')
                setSeizureLatchActive(true)
                setSeizureLatchRemaining(30.0)
                seizureLatchStartRef.current = Date.now()
              }
            } else {
              if (prevStatus === 'SEIZURE') {
                setSeizureLatchActive(false)
                setSeizureLatchRemaining(0.0)
                seizureLatchStartRef.current = null
              }
            }
          }
        } catch (err) {
          console.error(err)
        }
      }

      ws.onerror = (err) => {
        addLog('Seizure Svc', `WebSocket error: ${err.message || 'Unknown'}`, 'danger')
      }

      ws.onclose = () => {
        addLog('Seizure Svc', 'WebSocket closed.', 'info')
        setIsSeizureActive(false)
      }

    } catch (err) {
      setIsUploading(false)
      addLog('Seizure Svc', `Failed to start seizure test: ${err.message}`, 'danger')
      setIsSeizureActive(false)
    }
  }

  const stopSeizureTest = async () => {
    if (seizureWsRef.current) {
      seizureWsRef.current.close()
      seizureWsRef.current = null
    }
    setIsSeizureActive(false)
    setSeizureStatus('INITIALISING')
    setSeizureReady(false)
    setSeizureSignal(0.0)
    setSeizureRisk(0.0)
    setCjProb(0.0)
    setSeizureLatchActive(false)
    setSeizureLatchRemaining(0.0)
    seizureLatchStartRef.current = null
    eventBufferRef.current = []
    loggedSecsRef.current.clear()
    useAlertsStore.getState().stopAlarmSound()
    addLog('Seizure Svc', 'Seizure detection test stopped.', 'info')

    if (inputMode === 'video' && videoRef.current) {
      videoRef.current.pause()
    }

    if (isLive && selectedPatientId) {
      try {
        await http.delete(`/api/monitoring/seizure/${selectedPatientId}/stop`)
      } catch (err) {
        console.warn('Failed to delete seizure session:', err.message)
      }
    }
  }

  const handleResolveSeizureLatch = async () => {
    if (!isLive) {
      setSeizureLatchActive(false)
      setSeizureLatchRemaining(0.0)
      setSeizureStatus('NORMAL')
      useAlertsStore.getState().stopAlarmSound()
      addLog('Seizure Svc', '[MOCK] Seizure latch manually resolved by staff.', 'success')
      return
    }

    try {
      await http.post(`/api/monitoring/seizure/${selectedPatientId}/reset-latch`)
      setSeizureLatchActive(false)
      setSeizureLatchRemaining(0.0)
      setSeizureStatus('NORMAL')
      useAlertsStore.getState().stopAlarmSound()
      addLog('Seizure Svc', 'Seizure latch manually resolved by staff.', 'success')
    } catch (err) {
      addLog('Seizure Svc', `Failed to resolve seizure latch: ${err.message}`, 'danger')
    }
  }

  const handleResolveFallLatch = async () => {
    if (!isLive) {
      mockLatchRef.current = { active: false, startTime: null, streak: 0 }
      setFallLatchActive(false)
      setFallLatchRemaining(0.0)
      setFallStatus('NORMAL')
      useAlertsStore.getState().stopAlarmSound()
      addLog('Fall Svc', '[MOCK] Fall latch manually resolved by staff.', 'success')
      return
    }

    try {
      await http.post(`/api/monitoring/fall/sandbox_${selectedPatientId}/reset-latch`)
      setFallLatchActive(false)
      setFallLatchRemaining(0.0)
      setFallStatus('NORMAL')
      useAlertsStore.getState().stopAlarmSound()
      addLog('Fall Svc', 'Fall latch manually resolved by staff.', 'success')
    } catch (err) {
      addLog('Fall Svc', `Failed to resolve fall latch: ${err.message}`, 'danger')
    }
  }

  const triggerMockAnomaly = () => {
    if (!isLive) {
      if (isFallActive) {
        setFallProb(0.96)
        setFallStatus('FALL')
        addLog('Fall Svc', '⚠️ [MOCK MANUAL TRIGGER] Fall anomaly generated (96%)', 'danger')
      }
      if (isSeizureActive) {
        setSeizureStatus('SEIZURE')
        setSeizureSignal(0.92)
        setSeizureRisk(0.95)
        setSeizureLatchActive(true)
        setSeizureLatchRemaining(30.0)
        seizureLatchStartRef.current = Date.now()
        addLog('Seizure Svc', '⚠️ [MOCK MANUAL TRIGGER] Seizure signal anomaly generated (92%)', 'danger')
      }
    } else {
      addLog('Sandbox', 'Manual mock triggers are only available in Mock Data Mode.', 'warning')
    }
  }

  // ── ECG / Arrhythmia Test ──────────────────────────────────────────────────
  
  // Translate abbreviation to full name
  const _translateArrhythmia = (abbr) => {
    const map = {
      'AF': 'Atrial Fibrillation',
      'IAVB': 'First-Degree Atrioventricular Block',
      'SB': 'Sinus Bradycardia',
      'STach': 'Sinus Tachycardia'
    }
    return map[abbr] || abbr
  }

  // Load available ECG signals when switching tab
  useEffect(() => {
    if (activeTab === 'ecg' && ecgRecords.length === 0) {
      const fetchRecords = async () => {
        try {
          if (isLive) {
            const { data } = await http.get('/api/arrhythmia/sandbox/signals')
            setEcgRecords(data)
            if (data.length > 0) setSelectedRecord(data[0])
          } else {
            const mockRecs = ['02000_lr', '02001_lr', '02002_lr', '02003_lr', '02004_lr']
            setEcgRecords(mockRecs)
            setSelectedRecord(mockRecs[0])
          }
        } catch (err) {
          addLog('System', `Failed to load sandbox ECG records: ${err.message}`, 'danger')
          // Mock fallback
          const mockRecs = ['02000_lr', '02001_lr', '02002_lr', '02003_lr', '02004_lr']
          setEcgRecords(mockRecs)
          setSelectedRecord(mockRecs[0])
        }
      }
      fetchRecords()
    }
  }, [activeTab, isLive])

  // ECG streaming tick
  const ecgSignalDataRef = useRef([])
  const ecgSampleIndexRef = useRef(0)
  const ecgAlarmTimeoutRef = useRef(null)
  useEffect(() => {
    ecgSignalDataRef.current = ecgSignalData
  }, [ecgSignalData])

  useEffect(() => {
    if (!isEcgStreaming) return
    
    const tickInterval = 30 // ms
    const step = 15 // samples per tick
    
    const id = setInterval(() => {
      const current = ecgSampleIndexRef.current
      const next = current + step
      
      if (next >= 5000) {
        clearInterval(id)
        ecgSampleIndexRef.current = 5000
        setEcgSampleIndex(5000)
        setIsEcgStreaming(false)
        analyzeEcgSignal(ecgSignalDataRef.current)
      } else {
        ecgSampleIndexRef.current = next
        setEcgSampleIndex(next)
      }
    }, tickInterval)
    
    return () => clearInterval(id)
  }, [isEcgStreaming])

  const startEcgStream = async () => {
    if (!selectedPatientId) {
      addLog('Arrhythmia Svc', 'Please select a patient first.', 'warning')
      return
    }
    if (!selectedRecord) {
      addLog('Arrhythmia Svc', 'Please select an ECG record first.', 'warning')
      return
    }
    
    addLog('Arrhythmia Svc', `Loading ECG signal record: ${selectedRecord}...`, 'info')
    
    try {
      if (isLive) {
        const { data } = await http.get(`/api/arrhythmia/sandbox/signals/${selectedRecord}`)
        setEcgSignalData(data.signal)
        setEcgLeads(data.leads)
        setEcgSampleIndex(0)
        ecgSampleIndexRef.current = 0
        setEcgResult(null)
        setIsEcgStreaming(true)
        addLog('Arrhythmia Svc', 'ECG signal loaded. Starting live stream...', 'success')
      } else {
        // Mock Signal Generation
        addLog('Arrhythmia Svc', '[MOCK] Generating simulated ECG signal...', 'info')
        const synthetic = []
        for (let i = 0; i < 5000; i++) {
          const row = []
          const heartRate = 72
          const beatsPerSec = heartRate / 60
          const phase = (i / 500) * beatsPerSec * 2 * Math.PI
          const base = Math.sin(phase) * 0.1
          const qrs = Math.abs(Math.sin(phase)) > 0.95 ? (Math.random() > 0.5 ? 2.5 : -1.8) : 0.0
          const t_wave = Math.sin(phase - 1.0) * 0.25
          const noise = (Math.random() - 0.5) * 0.05
          for (let l = 0; l < 12; l++) {
            row.push(base + qrs * (1.0 - l*0.05) + t_wave + noise)
          }
          synthetic.push(row)
        }
        setEcgSignalData(synthetic)
        setEcgLeads(['I', 'II', 'III', 'AVR', 'AVL', 'AVF', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6'])
        setEcgSampleIndex(0)
        ecgSampleIndexRef.current = 0
        setEcgResult(null)
        setIsEcgStreaming(true)
        addLog('Arrhythmia Svc', '[MOCK] ECG signal ready. Starting live stream...', 'success')
      }
    } catch (err) {
      addLog('Arrhythmia Svc', `Failed to load ECG signal data: ${err.message}`, 'danger')
    }
  }

  function stopEcgStream() {
    setIsEcgStreaming(false)
    setEcgSampleIndex(0)
    ecgSampleIndexRef.current = 0
    setEcgResult(null)
    if (ecgAlarmTimeoutRef.current) {
      clearTimeout(ecgAlarmTimeoutRef.current)
      ecgAlarmTimeoutRef.current = null
    }
    useAlertsStore.getState().stopAlarmSound()
    addLog('Arrhythmia Svc', 'ECG stream stopped.', 'info')
  }

  const analyzeEcgSignal = async (signalData) => {
    const dataToAnalyze = signalData || ecgSignalData
    if (!dataToAnalyze || dataToAnalyze.length === 0) return
    
    setIsEcgAnalyzing(true)
    addLog('Arrhythmia Svc', 'ECG stream complete. Submitting signal for analysis...', 'info')
    
    try {
      if (isLive) {
        const res = await http.post('/api/arrhythmia/analyze', {
          patient_id: Number(selectedPatientId),
          signal: dataToAnalyze
        })
        
        setEcgResult(res.data)
        setIsEcgAnalyzing(false)
        
        if (res.data.stage1 === 'Abnormal') {
          addLog('Arrhythmia Svc', `⚠️ Arrhythmia detected! Subtype: ${res.data.stage2_class} (${_translateArrhythmia(res.data.stage2_class)})`, 'danger')
          
          if (ecgAlarmTimeoutRef.current) {
            clearTimeout(ecgAlarmTimeoutRef.current)
          }
          useAlertsStore.getState().playAlarmSound()
          ecgAlarmTimeoutRef.current = setTimeout(() => {
            useAlertsStore.getState().stopAlarmSound()
            ecgAlarmTimeoutRef.current = null
          }, 8000)
        } else {
          addLog('Arrhythmia Svc', 'ECG screening Normal. Patient rhythm is stable.', 'success')
        }
      } else {
        // Mock analysis result
        setTimeout(() => {
          const isAbnormal = Math.random() > 0.5
          const mockResult = {
            alert_id: isAbnormal ? 999 : null,
            patient_id: Number(selectedPatientId),
            stage1: isAbnormal ? 'Abnormal' : 'Normal',
            stage1_confidence: 0.945,
            stage2_class: isAbnormal ? ['AF', 'IAVB', 'SB', 'STach'][Math.floor(Math.random() * 4)] : null,
            stage2_confidence: isAbnormal ? 0.88 : null,
            all_probabilities: {
              binary: { 'Normal': isAbnormal ? 0.055 : 0.945, 'Abnormal': isAbnormal ? 0.945 : 0.055 },
              subtype: isAbnormal ? { 'AF': 0.15, 'IAVB': 0.1, 'SB': 0.1, 'STach': 0.65 } : {}
            },
            alert_created: isAbnormal,
            error: null
          }
          
          setEcgResult(mockResult)
          setIsEcgAnalyzing(false)
          
          if (isAbnormal) {
            addLog('Arrhythmia Svc', `⚠️ [MOCK] Arrhythmia detected! Subtype: ${mockResult.stage2_class} (${_translateArrhythmia(mockResult.stage2_class)})`, 'danger')
            
            if (ecgAlarmTimeoutRef.current) {
              clearTimeout(ecgAlarmTimeoutRef.current)
            }
            useAlertsStore.getState().playAlarmSound()
            ecgAlarmTimeoutRef.current = setTimeout(() => {
              useAlertsStore.getState().stopAlarmSound()
              ecgAlarmTimeoutRef.current = null
            }, 8000)
          } else {
            addLog('Arrhythmia Svc', '[MOCK] ECG screening Normal. Patient rhythm is stable.', 'success')
          }
        }, 1500)
      }
    } catch (err) {
      setIsEcgAnalyzing(false)
      addLog('Arrhythmia Svc', `Analysis failed: ${err.message}`, 'danger')
    }
  }

  const getEcgChartData = () => {
    if (!ecgSignalData || ecgSignalData.length === 0) return []
    const windowSize = 1000
    const start = Math.max(0, ecgSampleIndex - windowSize)
    const slice = ecgSignalData.slice(start, ecgSampleIndex)
    return slice.map((sample, idx) => ({
      name: start + idx,
      value: sample[selectedLeadIndex] || 0
    }))
  }

  const ecgChartData = getEcgChartData()

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-white p-6 rounded-2xl border border-navy-100 shadow-sm">
        <div>
          <h1 className="text-2xl font-heading font-bold text-navy-900 flex items-center gap-2">
            <Camera className="text-teal-600" />
            Model Testing Sandbox
          </h1>
          <p className="text-navy-500 text-sm mt-1">
            Test the live arrhythmia ECG, CTR-GCN fall detection, and VSViG/Cross-Joint seizure detection models.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-3 py-1 rounded-full text-xs font-semibold ${isLive ? 'bg-teal-50 text-teal-700 border border-teal-200' : 'bg-orange-50 text-orange-700 border border-orange-200'}`}>
            {isLive ? 'Live Connection Mode' : 'Mock Simulation Mode'}
          </span>
        </div>
      </div>

      {/* Tab Switcher */}
      <div className="flex gap-4 border-b border-navy-200">
        <button
          onClick={() => { setActiveTab('vision'); stopEcgStream(); }}
          className={`pb-3 font-heading font-semibold text-sm transition-all border-b-2 px-1 ${activeTab === 'vision' ? 'border-teal-600 text-teal-600' : 'border-transparent text-navy-400 hover:text-navy-700'}`}
        >
          Vision Models (Fall & Seizure)
        </button>
        <button
          onClick={() => { setActiveTab('ecg'); stopFallTest(); stopSeizureTest(); stopWebcam(); }}
          className={`pb-3 font-heading font-semibold text-sm transition-all border-b-2 px-1 ${activeTab === 'ecg' ? 'border-teal-600 text-teal-600' : 'border-transparent text-navy-400 hover:text-navy-700'}`}
        >
          ECG Model (Arrhythmia)
        </button>
      </div>

      {activeTab === 'vision' ? (
        /* Main Grid */
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Camera Screen */}
          <div className="lg:col-span-7 space-y-6">
            <div className="bg-navy-950 rounded-2xl overflow-hidden shadow-lg border border-navy-800 relative aspect-video flex items-center justify-center">
              {/* Live indicator */}
              {(isFallActive || isSeizureActive) && (
                <div className="absolute top-4 left-4 z-10 flex items-center gap-2 px-2.5 py-1 rounded-md bg-red-600/90 text-white text-[11px] font-bold tracking-wider uppercase animate-pulse">
                  <span className="w-1.5 h-1.5 rounded-full bg-white" />
                  Live Feed
                </div>
              )}
              
              <video
                ref={videoRef}
                playsInline
                muted
                onTimeUpdate={handleTimeUpdate}
                className="w-full h-full object-cover"
              />

              {!streamRef.current && !localVideoUrl && (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 bg-navy-900/60 backdrop-blur-sm text-navy-200">
                  <div className="w-12 h-12 rounded-full bg-navy-800 flex items-center justify-center border border-navy-700 text-teal-400 mb-3">
                    <Video size={24} />
                  </div>
                  <p className="font-medium">Media Source Inactive</p>
                  <p className="text-xs text-navy-400 max-w-xs mt-1">
                    Start the Fall or Seizure test below to load webcam or play the selected video file.
                  </p>
                </div>
              )}

              {isUploading && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-navy-950/80 backdrop-blur-sm text-white space-y-3">
                  <Loader2 size={32} className="text-teal-500 animate-spin" />
                  <p className="text-sm font-medium">Uploading video to server workspace...</p>
                </div>
              )}

              {isSeizureActive && !seizureReady && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-navy-950/80 backdrop-blur-sm text-white space-y-3 text-center p-6">
                  <Loader2 size={32} className="text-teal-500 animate-spin" />
                  <p className="text-sm font-medium text-teal-400">Initializing seizure detection pipeline...</p>
                  <p className="text-xs text-navy-300 max-w-xs">
                    Rebuilding ONNX sessions and warming up models. Playback will begin automatically when the first decision is made. (~6–10s)
                  </p>
                </div>
              )}
            </div>

            {/* Configuration Panel */}
            <div className="bg-white p-6 rounded-2xl border border-navy-100 shadow-sm space-y-6">
              <div>
                <h3 className="font-heading font-semibold text-navy-950 text-sm mb-3">Input Source Mode</h3>
                <div className="flex gap-2 p-1 bg-navy-50 rounded-xl border border-navy-100">
                  <button
                    onClick={() => { setInputMode('webcam'); stopFallTest(); stopSeizureTest(); stopWebcam(); }}
                    disabled={isFallActive || isSeizureActive}
                    className={`flex-1 py-2 px-3 rounded-lg text-xs font-semibold transition-all ${inputMode === 'webcam' ? 'bg-white text-navy-900 shadow-sm' : 'text-navy-500 hover:text-navy-900'}`}
                  >
                    System Webcam
                  </button>
                  <button
                    onClick={() => { setInputMode('video'); stopFallTest(); stopSeizureTest(); stopWebcam(); }}
                    disabled={isFallActive || isSeizureActive}
                    className={`flex-1 py-2 px-3 rounded-lg text-xs font-semibold transition-all ${inputMode === 'video' ? 'bg-white text-navy-900 shadow-sm' : 'text-navy-500 hover:text-navy-900'}`}
                  >
                    Upload Video File
                  </button>
                </div>
              </div>

              {/* Video File Uploader */}
              {inputMode === 'video' && (
                <div className="p-4 rounded-xl border border-dashed border-navy-300 bg-navy-50/50 flex flex-col items-center justify-center text-center">
                  <Upload size={24} className="text-navy-400 mb-2" />
                  <label className="cursor-pointer text-xs font-semibold text-teal-600 hover:text-teal-700">
                    Choose Video File
                    <input
                      type="file"
                      accept="video/*"
                      onChange={handleVideoSelect}
                      disabled={isFallActive || isSeizureActive}
                      className="hidden"
                    />
                  </label>
                  {selectedVideoFile ? (
                    <div className="space-y-1.5 mt-2">
                      <p className="text-navy-600 text-xs font-medium flex items-center gap-1.5 bg-white py-1 px-2.5 rounded border border-navy-100">
                        <FileVideo size={13} className="text-teal-600" />
                        {selectedVideoFile.name}
                      </p>
                      {backgroundUploadStatus === 'uploading' && (
                        <p className="text-teal-600 text-[10px] font-semibold flex items-center justify-center gap-1">
                          <Loader2 size={10} className="animate-spin" /> Uploading in background...
                        </p>
                      )}
                      {backgroundUploadStatus === 'ready' && (
                        <p className="text-green-600 text-[10px] font-semibold flex items-center justify-center gap-1">
                          ✓ Uploaded and ready
                        </p>
                      )}
                      {backgroundUploadStatus === 'failed' && (
                        <p className="text-red-600 text-[10px] font-semibold flex items-center justify-center gap-1">
                          ✗ Upload failed (will retry on start)
                        </p>
                      )}
                    </div>
                  ) : (
                    <p className="text-navy-400 text-[11px] mt-1">MP4, WEBM, or AVI files supported</p>
                  )}
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-navy-500 font-medium mb-1">Target Patient</label>
                  <select
                    value={selectedPatientId}
                    onChange={(e) => setSelectedPatientId(e.target.value)}
                    disabled={isFallActive || isSeizureActive}
                    className="w-full bg-navy-50 text-navy-900 rounded-lg px-3 py-2 border border-navy-200 text-sm focus:outline-none focus:ring-1 focus:ring-teal-600 disabled:opacity-50"
                  >
                    <option value="">Select Patient...</option>
                    {patients.map((p) => (
                      <option key={p.id} value={p.id}>{p.name} (ID: {p.id})</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs text-navy-500 font-medium mb-1">Webcam Index / RTSP URL</label>
                  <input
                    type="text"
                    value={seizureSource}
                    onChange={(e) => setSeizureSource(e.target.value)}
                    disabled={isSeizureActive || inputMode === 'video'}
                    placeholder="0 (Webcam) or RTSP url"
                    className="w-full bg-navy-50 text-navy-900 rounded-lg px-3 py-2 border border-navy-200 text-sm focus:outline-none focus:ring-1 focus:ring-teal-600 disabled:opacity-50"
                  />
                </div>
              </div>

              <div className="flex flex-wrap gap-3 pt-2">
                {!isFallActive ? (
                  <button
                    onClick={startFallTest}
                    disabled={isSeizureActive || (inputMode === 'video' && !selectedVideoFile)}
                    className="flex-1 min-w-[150px] flex items-center justify-center gap-2 bg-teal-600 hover:bg-teal-700 disabled:bg-navy-100 disabled:text-navy-400 text-white font-semibold text-xs px-4 py-2.5 rounded-lg transition-colors"
                  >
                    <Play size={14} /> Start Fall Detection
                  </button>
                ) : (
                  <button
                    onClick={stopFallTest}
                    className="flex-1 min-w-[150px] flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 text-white font-semibold text-xs px-4 py-2.5 rounded-lg transition-colors"
                  >
                    <Square size={14} /> Stop Fall Detection
                  </button>
                )}

                {!isSeizureActive ? (
                  <button
                    onClick={startSeizureTest}
                    disabled={isFallActive || (inputMode === 'video' && !selectedVideoFile)}
                    className="flex-1 min-w-[150px] flex items-center justify-center gap-2 bg-teal-600 hover:bg-teal-700 disabled:bg-navy-100 disabled:text-navy-400 text-white font-semibold text-xs px-4 py-2.5 rounded-lg transition-colors"
                  >
                    <Play size={14} /> Start Seizure Detection
                  </button>
                ) : (
                  <button
                    onClick={stopSeizureTest}
                    className="flex-1 min-w-[150px] flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 text-white font-semibold text-xs px-4 py-2.5 rounded-lg transition-colors"
                  >
                    <Square size={14} /> Stop Seizure Detection
                  </button>
                )}

                {!isLive && (isFallActive || isSeizureActive) && (
                  <button
                    onClick={triggerMockAnomaly}
                    className="flex items-center gap-2 bg-orange-600 hover:bg-orange-700 text-white font-semibold text-xs px-4 py-2.5 rounded-lg transition-colors"
                  >
                    <AlertTriangle size={14} /> Trigger Anomaly
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Right Column: Analytics & Live Outputs */}
          <div className="lg:col-span-5 space-y-6">
            {/* Fall Metrics Panel */}
            <div className={`bg-white p-6 rounded-2xl border border-navy-100 shadow-sm transition-all ${isFallActive ? 'ring-1 ring-teal-600' : 'opacity-60'}`}>
              <div className="flex justify-between items-start">
                <div>
                  <span className="text-[10px] uppercase font-bold tracking-wider text-navy-400">Pipeline 1</span>
                  <h2 className="text-base font-heading font-bold text-navy-900 mt-0.5">CTR-GCN Fall Classifier</h2>
                </div>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${isFallActive ? 'bg-teal-100 text-teal-800' : 'bg-navy-100 text-navy-600'}`}>
                  {isFallActive ? 'ACTIVE' : 'INACTIVE'}
                </span>
              </div>

              <div className="mt-4 space-y-3">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-navy-500 font-medium">Status</span>
                  <span className={`font-bold px-2 py-0.5 rounded text-xs ${fallStatus === 'FALL' ? 'bg-red-100 text-red-700 animate-pulse' : 'bg-green-100 text-green-700'}`}>
                    {fallStatus}
                  </span>
                </div>

                <div className="flex justify-between items-center text-sm">
                  <span className="text-navy-500 font-medium">Latch Status</span>
                  <span className={`font-semibold px-2 py-0.5 rounded text-xs ${fallLatchActive ? 'bg-amber-100 text-amber-800' : 'bg-navy-100 text-navy-600'}`}>
                    {fallLatchActive ? 'LATCHED' : 'NO LATCH'}
                  </span>
                </div>

                <div>
                  <div className="flex justify-between items-center text-xs text-navy-500 mb-1">
                    <span>Fall Probability (CTR-GCN output)</span>
                    <span className="font-semibold text-navy-900">{(fallProb * 100).toFixed(1)}%</span>
                  </div>
                  <div className="w-full bg-navy-50 h-2 rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all duration-300 ${fallProb > 0.85 ? 'bg-red-500' : fallProb > 0.5 ? 'bg-yellow-500' : 'bg-teal-600'}`}
                      style={{ width: `${fallProb * 100}%` }}
                    />
                  </div>
                </div>

                {fallLatchActive && (
                  <div className="mt-2 p-3 bg-amber-50 rounded-xl border border-amber-200 space-y-2">
                    <div className="flex justify-between items-center text-xs text-amber-805 font-semibold">
                      <span>Alert Latch Active — {Math.ceil(fallLatchRemaining)}s remaining</span>
                    </div>
                    <div className="h-1.5 bg-amber-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-amber-500 rounded-full transition-all duration-300"
                        style={{ width: `${(fallLatchRemaining / 30) * 100}%` }}
                      />
                    </div>
                    <button
                      onClick={handleResolveFallLatch}
                      className="w-full bg-amber-600 hover:bg-amber-700 text-white font-bold text-xs py-1.5 px-3 rounded-lg transition-colors shadow-sm"
                    >
                      Resolve Latch / Stop Alarm
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Seizure Metrics Panel */}
            <div className={`bg-white p-6 rounded-2xl border border-navy-100 shadow-sm transition-all ${isSeizureActive ? 'ring-1 ring-teal-600' : 'opacity-60'}`}>
              <div className="flex justify-between items-start">
                <div>
                  <span className="text-[10px] uppercase font-bold tracking-wider text-navy-400">Pipeline 2</span>
                  <h2 className="text-base font-heading font-bold text-navy-900 mt-0.5">Series Gate Seizure Detection</h2>
                </div>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${isSeizureActive ? 'bg-teal-100 text-teal-800' : 'bg-navy-100 text-navy-600'}`}>
                  {isSeizureActive ? 'ACTIVE' : 'INACTIVE'}
                </span>
              </div>

              <div className="mt-4 space-y-3">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-navy-500 font-medium">Model Status</span>
                  <span className={`font-bold px-2 py-0.5 rounded text-xs ${
                    seizureStatus === 'SEIZURE' ? 'bg-red-100 text-red-700 animate-pulse' :
                    seizureStatus === 'INITIALISING' ? 'bg-yellow-100 text-yellow-700 animate-pulse' :
                    'bg-green-100 text-green-700'
                  }`}>
                    {seizureStatus}
                  </span>
                </div>

                <div className="flex justify-between items-center text-sm">
                  <span className="text-navy-500 font-medium">Latch Status</span>
                  <span className={`font-semibold px-2 py-0.5 rounded text-xs ${seizureLatchActive ? 'bg-amber-100 text-amber-800' : 'bg-navy-100 text-navy-600'}`}>
                    {seizureLatchActive ? 'LATCHED' : 'NO LATCH'}
                  </span>
                </div>

                <div>
                  <div className="flex justify-between items-center text-xs text-navy-500 mb-1">
                    <span>Gate Score</span>
                    <span className="font-semibold text-navy-900">{seizureSignal.toFixed(3)}</span>
                  </div>
                  <div className="w-full bg-navy-50 h-2 rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all duration-300 ${seizureSignal > 0.8 ? 'bg-red-500' : seizureSignal > 0.4 ? 'bg-yellow-500' : 'bg-teal-600'}`}
                      style={{ width: `${seizureSignal * 100}%` }}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 pt-1">
                  <div>
                    <span className="block text-[10px] text-navy-400 uppercase font-medium">VSVIG Prob</span>
                    <span className="text-sm font-semibold text-navy-800">{seizureRisk.toFixed(3)}</span>
                  </div>
                  <div>
                    <span className="block text-[10px] text-navy-400 uppercase font-medium">Cross-Joint Prob</span>
                    <span className="text-sm font-semibold text-navy-800">{cjProb.toFixed(3)}</span>
                  </div>
                </div>

                {seizureLatchActive && (
                  <div className="mt-2 p-3 bg-amber-50 rounded-xl border border-amber-200 space-y-2">
                    <div className="flex justify-between items-center text-xs text-amber-805 font-semibold">
                      <span>Alert Latch Active — {Math.ceil(seizureLatchRemaining)}s remaining</span>
                    </div>
                    <div className="h-1.5 bg-amber-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-amber-500 rounded-full transition-all duration-300"
                        style={{ width: `${(seizureLatchRemaining / 30) * 100}%` }}
                      />
                    </div>
                    <button
                      onClick={handleResolveSeizureLatch}
                      className="w-full bg-amber-600 hover:bg-amber-700 text-white font-bold text-xs py-1.5 px-3 rounded-lg transition-colors shadow-sm"
                    >
                      Resolve Latch / Stop Alarm
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Console Output */}
            <div className="bg-white p-6 rounded-2xl border border-navy-100 shadow-sm flex flex-col h-[280px]">
              <h3 className="font-heading font-semibold text-navy-950 text-sm mb-3">Live Log Feed</h3>
              
              <div className="flex-1 overflow-y-auto space-y-2 font-mono text-[11px] bg-navy-950 text-navy-200 p-4 rounded-xl border border-navy-850 font-normal">
                {logs.length === 0 ? (
                  <div className="text-navy-500 text-center py-12 italic">
                    No logs generated yet. Start a test session above.
                  </div>
                ) : (
                  logs.map((log) => (
                    <div key={log.id} className="flex gap-2 leading-relaxed">
                      <span className="text-navy-500 shrink-0">[{log.time}]</span>
                      <span className={`font-bold shrink-0 ${
                        log.type === 'danger' ? 'text-red-400' :
                        log.type === 'success' ? 'text-teal-400' :
                        log.type === 'warning' ? 'text-orange-400' :
                        'text-sky-400'
                      }`}>
                        [{log.service}]
                      </span>
                      <span className="break-all">{log.message}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* ECG Layout Grid */
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 animate-fade-in">
          {/* Left Column: ECG Monitor */}
          <div className="lg:col-span-8 space-y-6">
            <div className="bg-navy-950 rounded-2xl p-6 shadow-lg border border-navy-800 relative flex flex-col justify-between">
              {/* Live indicator / status */}
              <div className="flex justify-between items-center mb-4">
                <div className="flex items-center gap-2">
                  <span className={`w-2.5 h-2.5 rounded-full ${isEcgStreaming ? 'bg-red-500 animate-pulse' : 'bg-navy-700'}`} />
                  <span className="text-xs font-semibold uppercase tracking-wider text-navy-300">
                    {isEcgStreaming ? 'ECG Streaming Live' : 'ECG Monitor Idle'}
                  </span>
                </div>
                {isEcgStreaming && (
                  <span className="text-[11px] font-mono text-teal-400">
                    Time: {((ecgSampleIndex / 5000) * 10).toFixed(1)}s / 10s
                  </span>
                )}
              </div>

              {/* ECG Waveform Chart */}
              <div className="h-64 bg-navy-900 rounded-xl overflow-hidden border border-navy-800 p-2 flex items-center justify-center">
                {ecgChartData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={ecgChartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                      <YAxis domain={['auto', 'auto']} stroke="#64748b" tickFormatter={(v) => v.toFixed(1)} />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke="#10b981"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="text-center p-6 text-navy-400 space-y-2">
                    <Activity className="mx-auto text-navy-600 animate-pulse" size={32} />
                    <p className="text-xs">No active signal. Click "Start Live ECG Stream" below.</p>
                  </div>
                )}
              </div>

              {/* Lead selector (only shown when data is loaded) */}
              {ecgLeads.length > 0 && (
                <div className="mt-4">
                  <label className="text-[10px] uppercase font-bold tracking-wider text-navy-400 block mb-2">Display Lead</label>
                  <div className="flex flex-wrap gap-1.5">
                    {ecgLeads.map((lead, idx) => (
                      <button
                        key={lead}
                        onClick={() => setSelectedLeadIndex(idx)}
                        className={`px-2.5 py-1 rounded text-xs font-semibold transition-all ${selectedLeadIndex === idx ? 'bg-teal-500 text-white shadow-sm' : 'bg-navy-900 text-navy-400 hover:text-white'}`}
                      >
                        {lead}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Configuration Card */}
            <div className="bg-white p-6 rounded-2xl border border-navy-100 shadow-sm space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-navy-500 font-medium mb-1">Target Patient</label>
                  <select
                    value={selectedPatientId}
                    onChange={(e) => setSelectedPatientId(e.target.value)}
                    disabled={isEcgStreaming || isEcgAnalyzing}
                    className="w-full bg-navy-50 text-navy-900 rounded-lg px-3 py-2 border border-navy-200 text-sm focus:outline-none focus:ring-1 focus:ring-teal-600"
                  >
                    <option value="">Select Patient...</option>
                    {patients.map((p) => (
                      <option key={p.id} value={p.id}>{p.name} (ID: {p.id})</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs text-navy-500 font-medium mb-1">Select ECG Signal Record</label>
                  <select
                    value={selectedRecord}
                    onChange={(e) => setSelectedRecord(e.target.value)}
                    disabled={isEcgStreaming || isEcgAnalyzing}
                    className="w-full bg-navy-50 text-navy-900 rounded-lg px-3 py-2 border border-navy-200 text-sm focus:outline-none focus:ring-1 focus:ring-teal-600"
                  >
                    <option value="">Select Record...</option>
                    {ecgRecords.map((rec) => (
                      <option key={rec} value={rec}>{rec}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                {!isEcgStreaming ? (
                  <button
                    onClick={startEcgStream}
                    disabled={!selectedPatientId || !selectedRecord || isEcgAnalyzing}
                    className="flex-1 flex items-center justify-center gap-2 bg-teal-600 hover:bg-teal-700 disabled:bg-navy-100 disabled:text-navy-400 text-white font-semibold text-xs px-4 py-2.5 rounded-lg transition-colors"
                  >
                    <Play size={14} /> Start Live ECG Stream
                  </button>
                ) : (
                  <button
                    onClick={stopEcgStream}
                    className="flex-1 flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 text-white font-semibold text-xs px-4 py-2.5 rounded-lg transition-colors"
                  >
                    <Square size={14} /> Stop Stream
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Right Column: Classification Results */}
          <div className="lg:col-span-4 space-y-6">
            <div className={`bg-white p-6 rounded-2xl border border-navy-100 shadow-sm transition-all ${isEcgAnalyzing ? 'ring-1 ring-teal-600' : ''}`}>
              <div className="flex justify-between items-start">
                <div>
                  <span className="text-[10px] uppercase font-bold tracking-wider text-navy-400">Cascade Model</span>
                  <h2 className="text-base font-heading font-bold text-navy-900 mt-0.5">Arrhythmia Screening</h2>
                </div>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${isEcgStreaming ? 'bg-red-100 text-red-800 animate-pulse' : isEcgAnalyzing ? 'bg-yellow-100 text-yellow-800' : 'bg-navy-100 text-navy-600'}`}>
                  {isEcgStreaming ? 'STREAMING' : isEcgAnalyzing ? 'ANALYZING' : 'IDLE'}
                </span>
              </div>

              <div className="mt-4 space-y-4">
                {isEcgAnalyzing && !ecgResult && (
                  <div className="flex flex-col items-center justify-center py-8 text-navy-400 gap-2">
                    <Loader2 className="animate-spin text-teal-600" size={24} />
                    <p className="text-xs">Running inference cascade...</p>
                  </div>
                )}

                {ecgResult && (
                  <div className="space-y-4 animate-fade-in">
                    <div className="flex justify-between items-center text-sm border-b border-navy-50 pb-2">
                      <span className="text-navy-500 font-medium">Stage 1 Screening</span>
                      <span className={`font-bold px-2 py-0.5 rounded text-xs ${ecgResult.stage1 === 'Abnormal' ? 'bg-red-100 text-red-700 animate-pulse' : 'bg-green-100 text-green-700'}`}>
                        {ecgResult.stage1}
                      </span>
                    </div>

                    {ecgResult.stage1 === 'Abnormal' && (
                      <div className="flex justify-between items-center text-sm border-b border-navy-50 pb-2">
                        <span className="text-navy-500 font-medium">Stage 2 Subtype</span>
                        <span className="font-bold px-2 py-0.5 rounded text-xs bg-red-100 text-red-700">
                          {ecgResult.stage2_class} ({_translateArrhythmia(ecgResult.stage2_class)})
                        </span>
                      </div>
                    )}

                    <div className="space-y-2">
                      <span className="text-xs text-navy-500 font-medium block">Inference Probabilities</span>
                      {Object.entries(ecgResult.all_probabilities?.binary || {}).map(([cls, prob]) => (
                        <div key={cls} className="space-y-1">
                          <div className="flex justify-between text-[11px] text-navy-600">
                            <span>{cls}</span>
                            <span>{(prob * 100).toFixed(1)}%</span>
                          </div>
                          <div className="w-full bg-navy-50 h-1.5 rounded-full overflow-hidden">
                            <div
                              className={`h-full ${cls === 'Abnormal' ? 'bg-red-500' : 'bg-green-500'}`}
                              style={{ width: `${prob * 100}%` }}
                            />
                          </div>
                        </div>
                      ))}
                      
                      {ecgResult.stage1 === 'Abnormal' && Object.entries(ecgResult.all_probabilities?.subtype || {}).map(([cls, prob]) => (
                        <div key={cls} className="space-y-1">
                          <div className="flex justify-between text-[11px] text-navy-600">
                            <span>{cls} ({_translateArrhythmia(cls)})</span>
                            <span>{(prob * 100).toFixed(1)}%</span>
                          </div>
                          <div className="w-full bg-navy-50 h-1.5 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-orange-500"
                              style={{ width: `${prob * 100}%` }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>


                  </div>
                )}

                {!isEcgStreaming && !isEcgAnalyzing && !ecgResult && (
                  <div className="text-center py-12 text-navy-400 italic text-xs">
                    Awaiting signal streaming.
                  </div>
                )}
              </div>
            </div>
            
            {/* Console Output (shares logs feed) */}
            <div className="bg-white p-6 rounded-2xl border border-navy-100 shadow-sm flex flex-col h-[280px]">
              <h3 className="font-heading font-semibold text-navy-950 text-sm mb-3">Live Log Feed</h3>
              
              <div className="flex-1 overflow-y-auto space-y-2 font-mono text-[11px] bg-navy-950 text-navy-200 p-4 rounded-xl border border-navy-850 font-normal">
                {logs.length === 0 ? (
                  <div className="text-navy-500 text-center py-12 italic">
                    No logs generated yet.
                  </div>
                ) : (
                  logs.map((log) => (
                    <div key={log.id} className="flex gap-2 leading-relaxed">
                      <span className="text-navy-500 shrink-0">[{log.time}]</span>
                      <span className={`font-bold shrink-0 ${
                        log.type === 'danger' ? 'text-red-400' :
                        log.type === 'success' ? 'text-teal-400' :
                        log.type === 'warning' ? 'text-orange-400' :
                        'text-sky-400'
                      }`}>
                        [{log.service}]
                      </span>
                      <span className="break-all">{log.message}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
