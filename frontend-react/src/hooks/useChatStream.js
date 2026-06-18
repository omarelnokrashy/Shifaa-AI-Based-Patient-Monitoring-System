/**
 * useChatStream — manages a WebSocket connection for the streaming chat panel.
 *
 * Message protocol (mirrors the backend SSE/WS schema):
 *   { type: "think_start" }
 *   { type: "think",      chunk: "..." }
 *   { type: "think_done", duration: 3.2 }
 *   { type: "chunk",      chunk: "...", done: false }
 *   { type: "done",       done: true }
 *   { type: "error",      message: "..." }
 *
 * In mock mode the hook simulates streaming by splitting a canned response
 * into chunks and emitting them with setInterval.
 */
import { useCallback, useRef, useState } from 'react'
import useAuthStore from '../store/authStore'

const IS_MOCK  = import.meta.env.VITE_DATA_MODE !== 'live'
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS_BASE  = (import.meta.env.VITE_WS_URL || 'ws://localhost:8000')

const MOCK_THINK = `Analyzing the patient's records. The patient has Type 2 Diabetes with HbA1c of 7.8% which is above the ADA target of <7%. They are currently on Metformin 500mg twice daily. There are no contraindications noted. I should recommend dose optimization.`

const MOCK_RESPONSE = `Based on the latest lab results (HbA1c: **7.8%**, Fasting Glucose: **142 mg/dL**), glycaemic control remains suboptimal.

**Recommended actions:**
1. Increase Metformin to **1000mg twice daily** (patient can tolerate — creatinine is within normal limits).
2. Schedule repeat HbA1c in **3 months**.
3. Reinforce dietary counselling — Mediterranean diet pattern.
4. Consider adding a GLP-1 agonist if HbA1c remains ≥7.5% at next visit.

No drug interactions with current medications (Amlodipine). Penicillin allergy documented — not relevant here.`

export function useChatStream() {
  const token = useAuthStore((s) => s.token)
  const wsRef = useRef(null)

  const [messages,    setMessages]    = useState([])
  const [isThinking,  setIsThinking]  = useState(false)
  const [thinkText,   setThinkText]   = useState('')
  const [thinkDone,   setThinkDone]   = useState(null)  // { text, duration }
  const [isStreaming, setIsStreaming]  = useState(false)

  const addMessage = useCallback((msg) => {
    setMessages((prev) => [...prev, msg])
  }, [])

  // ── Mock streaming simulation ─────────────────────────────────────────────
  const _mockStream = useCallback((userMsg, patientId, mode) => {
    addMessage({ role: 'user', content: userMsg, id: Date.now() })

    // Phase 1: think
    setIsThinking(true)
    setThinkText('')
    setThinkDone(null)

    let thinkAcc = ''
    let thinkIdx = 0
    const thinkInterval = setInterval(() => {
      if (thinkIdx >= MOCK_THINK.length) {
        clearInterval(thinkInterval)
        setIsThinking(false)
        const duration = 2.3 + Math.random() * 1.5
        setThinkDone({ text: thinkAcc, duration: duration.toFixed(1) })

        // Phase 2: answer stream
        setIsStreaming(true)
        let ansAcc = ''
        let ansIdx = 0
        const answerInterval = setInterval(() => {
          if (ansIdx >= MOCK_RESPONSE.length) {
            clearInterval(answerInterval)
            setIsStreaming(false)
            addMessage({ role: 'bot', content: ansAcc, id: Date.now() })
            setMessages((prev) => prev.filter((m) => m.id !== 'streaming'))
            return
          }
          const chunk = MOCK_RESPONSE.slice(ansIdx, ansIdx + 4)
          ansAcc += chunk
          ansIdx += 4
          setMessages((prev) => {
            const existing = prev.find((m) => m.id === 'streaming')
            if (existing) return prev.map((m) => m.id === 'streaming' ? { ...m, content: ansAcc } : m)
            return [...prev, { role: 'bot', content: ansAcc, id: 'streaming', streaming: true }]
          })
        }, 18)
        return
      }
      const chunk = MOCK_THINK.slice(thinkIdx, thinkIdx + 6)
      thinkAcc += chunk
      thinkIdx += 6
      setThinkText(thinkAcc)
    }, 25)
  }, [addMessage])

  // ── Live WebSocket send ───────────────────────────────────────────────────
  const _liveStream = useCallback((userMsg, patientId, mode) => {
    addMessage({ role: 'user', content: userMsg, id: Date.now() })

    const ws = new WebSocket(`${WS_BASE}/api/chat/stream?token=${token}`)
    wsRef.current = ws
    let botAcc = ''

    ws.onopen = () => {
      ws.send(JSON.stringify({ query: userMsg, patient_id: patientId, mode }))
    }

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'think_start') { setIsThinking(true); setThinkText(''); setThinkDone(null) }
        if (msg.type === 'think')       { setThinkText((t) => t + msg.chunk) }
        if (msg.type === 'think_done')  { setIsThinking(false); setThinkDone({ text: '', duration: msg.duration }) }
        if (msg.type === 'chunk')       {
          botAcc += msg.chunk
          setIsStreaming(true)
          setMessages((prev) => {
            const existing = prev.find((m) => m.id === 'streaming')
            if (existing) return prev.map((m) => m.id === 'streaming' ? { ...m, content: botAcc } : m)
            return [...prev, { role: 'bot', content: botAcc, id: 'streaming', streaming: true }]
          })
        }
        if (msg.type === 'done') {
          setIsStreaming(false)
          addMessage({ role: 'bot', content: botAcc, id: Date.now() })
          setMessages((prev) => prev.filter((m) => m.id !== 'streaming'))
          ws.close()
        }
        if (msg.type === 'error') {
          addMessage({ role: 'bot', content: `⚠️ ${msg.message}`, id: Date.now(), isError: true })
          ws.close()
        }
      } catch { /* ignore */ }
    }

    ws.onerror = () => {
      addMessage({ role: 'bot', content: '⚠️ Connection error. Please try again.', id: Date.now(), isError: true })
      setIsStreaming(false)
      setIsThinking(false)
    }
  }, [token, addMessage])

  const sendMessage = useCallback((userMsg, patientId, mode = 'patient') => {
    if (!userMsg.trim() || isStreaming || isThinking) return
    if (IS_MOCK) _mockStream(userMsg, patientId, mode)
    else         _liveStream(userMsg, patientId, mode)
  }, [isStreaming, isThinking, _mockStream, _liveStream])

  const clearMessages = useCallback(() => {
    setMessages([])
    setIsThinking(false)
    setThinkText('')
    setThinkDone(null)
    setIsStreaming(false)
  }, [])

  return { messages, isThinking, thinkText, thinkDone, isStreaming, sendMessage, clearMessages }
}
