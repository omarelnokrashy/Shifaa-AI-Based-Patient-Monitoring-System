import { useState, useEffect, useRef } from 'react'
import { Camera, Video, AlertTriangle, Play, Square, Upload, FileVideo, Loader2 } from 'lucide-react'
import { http } from '../../api/client'
import useAuthStore from '../../store/authStore'

export default function SandboxTestPage() {
  const user = useAuthStore((s) => s.user)
  const isLive = import.meta.env.VITE_DATA_MODE === 'live'

  // Input configuration modes
  const [inputMode, setInputMode] = useState('webcam') // 'webcam' | 'video'
  const [selectedVideoFile, setSelectedVideoFile] = useState(null)
  const [localVideoUrl, setLocalVideoUrl] = useState('')
  const [isUploading, setIsUploading] = useState(false)

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
  
  // Console logs
  const [logs, setLogs] = useState([])

  // Webcams, video playing & loops
  const videoRef = useRef(null)
  const streamRef = useRef(null)
  const fallWsRef = useRef(null)
  const seizureWsRef = useRef(null)
  const intervalRef = useRef(null)

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
      if (localVideoUrl) {
        URL.revokeObjectURL(localVideoUrl)
      }
    }
  }, [localVideoUrl])

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
  const handleVideoSelect = (e) => {
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
    const url = URL.createObjectURL(file)
    setLocalVideoUrl(url)

    if (videoRef.current) {
      videoRef.current.srcObject = null
      videoRef.current.src = url
      videoRef.current.load()
    }
    addLog('Video', `Loaded file: ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`, 'success')
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
    
    if (inputMode === 'webcam') {
      const cameraReady = await startWebcam()
      if (!cameraReady) return
    } else {
      if (!selectedVideoFile) {
        addLog('Fall Svc', 'Please upload/select a video file first.', 'warning')
        return
      }
      if (videoRef.current) {
        videoRef.current.play()
      }
    }

    setIsFallActive(true)
    addLog('Fall Svc', `Starting fall detection stream using ${inputMode}...`, 'info')

    if (!isLive) {
      // Mock simulation loop
      addLog('Fall Svc', '[MOCK] Connected to mock fall stream.', 'success')
      let ticks = 0
      intervalRef.current = setInterval(() => {
        ticks++
        const mockProb = Math.min(1.0, Math.max(0.0, 0.1 + Math.sin(ticks / 5) * 0.15 + (Math.random() * 0.05)))
        setFallProb(mockProb)
        setFallStatus(mockProb > 0.85 ? 'FALL' : 'NORMAL')

        if (mockProb > 0.85 && ticks % 10 === 0) {
          addLog('Fall Svc', `⚠️ [MOCK] Anomaly alert generated with probability: ${(mockProb * 100).toFixed(1)}%`, 'danger')
        }
      }, 300)
      return
    }

    try {
      // 1. Create a session on backend
      const res = await http.post('/api/monitoring/fall/start', {
        room_id: 'sandbox_test',
        patient_id: Number(selectedPatientId),
      })
      addLog('Fall Svc', `Session created. Connecting bridge: ${res.data.ws_url}`, 'info')

      // 2. Connect WebSocket
      const wsUrl = `ws://${window.location.host}${res.data.ws_url}`
      const ws = new WebSocket(wsUrl)
      fallWsRef.current = ws

      ws.onopen = () => {
        addLog('Fall Svc', 'WebSocket bridge connected. Streaming frames...', 'success')
        
        // Setup frame sender loop
        const canvas = document.createElement('canvas')
        canvas.width = 320
        canvas.height = 240
        const ctx = canvas.getContext('2d')

        intervalRef.current = setInterval(() => {
          if (videoRef.current && (videoRef.current.readyState === 4 || videoRef.current.readyState === 3 || videoRef.current.readyState === 2)) {
            ctx.drawImage(videoRef.current, 0, 0, 320, 240)
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
    addLog('Fall Svc', 'Fall detection test stopped.', 'info')

    if (inputMode === 'video' && videoRef.current) {
      videoRef.current.pause()
    }

    if (isLive) {
      try {
        await http.delete('/api/monitoring/fall/sandbox_test/stop')
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
        if (videoRef.current) videoRef.current.play()
      }

      // Mock simulation loop
      addLog('Seizure Svc', '[MOCK] Connected to mock seizure WS.', 'success')
      let ticks = 0
      setSeizureStatus('INITIALISING')
      intervalRef.current = setInterval(() => {
        ticks++
        if (ticks < 10) {
          setSeizureStatus('INITIALISING')
          return
        }
        const mockSig = Math.min(1.0, Math.max(0.0, 0.05 + Math.sin(ticks / 7) * 0.1 + (Math.random() * 0.03)))
        setSeizureSignal(mockSig)
        setSeizureRisk(mockSig * 1.2)
        setCjProb(mockSig * 0.8)
        setSeizureStatus(mockSig > 0.8 ? 'SEIZURE' : 'NORMAL')

        if (mockSig > 0.8) {
          addLog('Seizure Svc', `⚠️ [MOCK] Seizure activity signature detected!`, 'danger')
        }
      }, 500)
      return
    }

    try {
      let finalSource = seizureSource

      // If we are in video mode, we must upload the video file to backend first
      if (inputMode === 'video') {
        if (!selectedVideoFile) {
          addLog('Seizure Svc', 'Please select a video file first.', 'warning')
          setIsSeizureActive(false)
          return
        }

        setIsUploading(true)
        addLog('Seizure Svc', 'Uploading video to server workspace...', 'info')

        const formData = new FormData()
        formData.append('file', selectedVideoFile)

        const uploadRes = await http.post('/api/monitoring/seizure/upload-test-video', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })

        finalSource = uploadRes.data.file_path
        setIsUploading(false)
        addLog('Seizure Svc', 'Video uploaded successfully to server path.', 'success')

        // Start playing locally in the browser
        if (videoRef.current) {
          videoRef.current.play()
        }
      }

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
          setSeizureStatus(data.status || 'INITIALISING')
          setSeizureSignal(data.gate_score || 0.0)
          setSeizureRisk(data.current_risk || 0.0)
          setCjProb(data.cj_prob || 0.0)
          
          if (data.status === 'SEIZURE') {
            addLog('Seizure Svc', `⚠️ Seizure active! Signal: ${data.gate_score?.toFixed(3)}`, 'danger')
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
    setSeizureSignal(0.0)
    setSeizureRisk(0.0)
    setCjProb(0.0)
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
        addLog('Seizure Svc', '⚠️ [MOCK MANUAL TRIGGER] Seizure signal anomaly generated (92%)', 'danger')
      }
    } else {
      addLog('Sandbox', 'Manual mock triggers are only available in Mock Data Mode.', 'warning')
    }
  }

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
            Test the live CTR-GCN fall detection and VSViG/Cross-Joint seizure detection models with custom streams.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-3 py-1 rounded-full text-xs font-semibold ${isLive ? 'bg-teal-50 text-teal-700 border border-teal-200' : 'bg-orange-50 text-orange-700 border border-orange-200'}`}>
            {isLive ? 'Live Connection Mode' : 'Mock Simulation Mode'}
          </span>
        </div>
      </div>

      {/* Main Grid */}
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
              autoPlay
              playsInline
              muted
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
                  <p className="text-navy-600 text-xs mt-2 font-medium flex items-center gap-1.5 bg-white py-1 px-2.5 rounded border border-navy-100">
                    <FileVideo size={13} className="text-teal-600" />
                    {selectedVideoFile.name}
                  </p>
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
            </div>
          </div>

          {/* Seizure Metrics Panel */}
          <div className={`bg-white p-6 rounded-2xl border border-navy-100 shadow-sm transition-all ${isSeizureActive ? 'ring-1 ring-teal-600' : 'opacity-60'}`}>
            <div className="flex justify-between items-start">
              <div>
                <span className="text-[10px] uppercase font-bold tracking-wider text-navy-400">Pipeline 2</span>
                <h2 className="text-base font-heading font-bold text-navy-900 mt-0.5">VSViG Seizure Monitor</h2>
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

              <div>
                <div className="flex justify-between items-center text-xs text-navy-500 mb-1">
                  <span>VSViG Signal (Gate Score)</span>
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
                  <span className="block text-[10px] text-navy-400 uppercase font-medium">Risk Score</span>
                  <span className="text-sm font-semibold text-navy-800">{seizureRisk.toFixed(3)}</span>
                </div>
                <div>
                  <span className="block text-[10px] text-navy-400 uppercase font-medium">Cross-Joint Prob</span>
                  <span className="text-sm font-semibold text-navy-800">{cjProb.toFixed(3)}</span>
                </div>
              </div>
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
    </div>
  )
}
