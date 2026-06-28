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
import { useCallback, useRef, useState, useEffect } from 'react'
import useAuthStore from '../store/authStore'
import { apiGetChatHistory, apiGetGeneralChatHistory } from '../api/client'

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

/**
 * React hook that manages a streaming AI chat session.
 *
 * Handles three message flows transparently:
 * - **Mock text** (`IS_MOCK && no image`): simulates think + answer streaming via timers.
 * - **Live text** (`!IS_MOCK && no image`): opens a WebSocket to `/api/chat/stream`.
 * - **Image** (any mode): POSTs a `multipart/form-data` request and reads an SSE stream.
 *
 * @returns {{
 *   messages:    Array<{role: string, content: string, id: number|string, streaming?: boolean, isError?: boolean, image?: string}>,
 *   isThinking:  boolean,
 *   thinkText:   string,
 *   thinkDone:   {text: string, duration: string|number}|null,
 *   isStreaming:  boolean,
 *   isImageAnalyzing: boolean,
 *   sendMessage:  Function,
 *   clearMessages: Function
 * }}
 */
export function useChatStream(patientId = null, mode = 'patient') {
  const token = useAuthStore((s) => s.token)
  const wsRef = useRef(null)

  const [messages,    setMessages]    = useState([])
  const [isThinking,  setIsThinking]  = useState(false)
  const [thinkText,   setThinkText]   = useState('')
  const [thinkDone,   setThinkDone]   = useState(null)  // { text, duration }
  const [isStreaming, setIsStreaming]  = useState(false)
  const [isImageAnalyzing, setIsImageAnalyzing] = useState(false)

  // Load chat history for patient-specific or general chat
  useEffect(() => {
    const parseQueryMessage = (log) => {
      let content = log.query
      let imageUrl = null
      
      if (log.query && log.query.startsWith('[Uploaded Image: ')) {
        const closeIdx = log.query.indexOf(']')
        if (closeIdx !== -1) {
          const val = log.query.slice(17, closeIdx).trim()
          if (val.startsWith('/uploads/') || val.startsWith('http') || val.includes('/chat_images/')) {
            imageUrl = val.startsWith('/') ? `${BASE_URL}${val}` : val
            content = log.query.slice(closeIdx + 1).trim()
          }
        }
      }
      
      return {
        role: 'user',
        content: content,
        image: imageUrl,
        id: `${log.id}-user`
      }
    }

    if (patientId && mode === 'patient') {
      apiGetChatHistory(patientId)
        .then((logs) => {
          const loaded = []
          logs.forEach((log) => {
            if (log.query) {
              loaded.push(parseQueryMessage(log))
            }
            if (log.response) {
              loaded.push({ role: 'bot', content: log.response, id: `${log.id}-bot` })
            }
          })
          setMessages(loaded)
        })
        .catch((err) => {
          console.error("Failed to load chat history:", err)
        })
    } else if (mode === 'general') {
      apiGetGeneralChatHistory()
        .then((logs) => {
          const loaded = []
          logs.forEach((log) => {
            if (log.query) {
              loaded.push(parseQueryMessage(log))
            }
            if (log.response) {
              loaded.push({ role: 'bot', content: log.response, id: `${log.id}-bot` })
            }
          })
          setMessages(loaded)
        })
        .catch((err) => {
          console.error("Failed to load general chat history:", err)
        })
    } else {
      setMessages([])
    }
  }, [patientId, mode])

  /**
   * Append a single message object to the conversation list.
   *
   * @param {{ role: string, content: string, id: number|string, isError?: boolean, image?: string }} msg
   *   The message to append.
   */
  const addMessage = useCallback((msg) => {
    setMessages((prev) => [...prev, msg])
  }, [])

  // ── Mock streaming simulation ─────────────────────────────────────────────
  /**
   * Simulate a think-then-answer streaming response using `setInterval` timers.
   * Updates `isThinking`, `thinkText`, `thinkDone`, and `isStreaming` state as
   * each phase progresses.
   *
   * @param {string} userMsg   - The user's message text.
   * @param {number|string|null} patientId - The active patient's ID (may be null).
   * @param {string} mode      - Chat mode (e.g. `'patient'` or `'general'`).
   */
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
  /**
   * Open a WebSocket to the live chat endpoint, send the query, and process
   * the streaming protocol frames (`think_start`, `think`, `think_done`,
   * `chunk`, `done`, `error`) into component state.
   *
   * @param {string} userMsg   - The user's message text.
   * @param {number|string|null} patientId - The active patient's ID.
   * @param {string} mode      - Chat mode passed to the backend.
   */
  const _liveStream = useCallback((userMsg, patientId, mode) => {
    addMessage({ role: 'user', content: userMsg, id: Date.now() })

    const ws = new WebSocket(`${WS_BASE}/api/chat/stream?token=${token}`)
    wsRef.current = ws
    let botAcc = ''
    let thinkAcc = ''

    ws.onopen = () => {
      ws.send(JSON.stringify({ query: userMsg, patient_id: patientId, mode }))
    }

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'think_start') {
          setIsThinking(true)
          setThinkText('')
          setThinkDone(null)
          thinkAcc = ''
        }
        if (msg.type === 'think') {
          thinkAcc += msg.chunk
          setThinkText(thinkAcc)
        }
        if (msg.type === 'think_done') {
          setIsThinking(false)
          setThinkDone({ text: thinkAcc, duration: msg.duration })
        }
        if (msg.type === 'chunk') {
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

  // ── Image SSE Stream (handles both Mock & Live) ───────────────────────────
  /**
   * Upload an image and stream the AI response via Server-Sent Events (SSE).
   * In mock mode the SSE is simulated with timers. In live mode, a
   * `multipart/form-data` POST is made to `/api/chat/analyze-image` and the
   * response body is read as a raw SSE stream.
   *
   * @param {File}   imageFile  - The image file selected by the user.
   * @param {string} imageType  - Category label for the image (e.g. `'xray'`, `'ecg'`, `'general'`).
   * @param {string} userMsg    - Accompanying question or context from the user.
   * @param {number|string|null} patientId - The active patient's ID.
   * @param {string} mode       - Chat mode passed to the backend.
   * @returns {Promise<void>}
   */
  const _imageStream = useCallback(async (imageFile, imageType, userMsg, patientId, mode) => {
    const imageUrl = URL.createObjectURL(imageFile)
    addMessage({ role: 'user', content: userMsg, image: imageUrl, id: Date.now() })

    // Use isStreaming as the send-gate (prevents double-sends).
    // Do NOT set isThinking — that causes a stuck "Thinking..." spinner.
    setIsStreaming(true)
    setIsImageAnalyzing(true)
    setThinkText('')
    setThinkDone(null)

    if (IS_MOCK) {
      let thinkAcc = ''
      let thinkIdx = 0
      const mockThink = `Mock mode is enabled, so the uploaded ${imageType} image is not being sent to MedGemma. Preparing a non-diagnostic demo response.`
      const mockResponse = `**Mock image-analysis mode**

This is not MedGemma image reasoning. The frontend is running with \`VITE_DATA_MODE\` set to mock, so the uploaded image was displayed locally but not analyzed by the backend multimodal model.

Switch the frontend to \`VITE_DATA_MODE=live\` and make sure the backend multimodal model is running to get real image reasoning.`

      const thinkInterval = setInterval(() => {
        if (thinkIdx >= mockThink.length) {
          clearInterval(thinkInterval)
          setIsImageAnalyzing(false)

          let ansAcc = ''
          let ansIdx = 0
          const answerInterval = setInterval(() => {
            if (ansIdx >= mockResponse.length) {
              clearInterval(answerInterval)
              setIsStreaming(false)
              addMessage({ role: 'bot', content: ansAcc, id: Date.now() })
              setMessages((prev) => prev.filter((m) => m.id !== 'streaming'))
              return
            }
            const chunk = mockResponse.slice(ansIdx, ansIdx + 5)
            ansAcc += chunk
            ansIdx += 5
            setMessages((prev) => {
              const existing = prev.find((m) => m.id === 'streaming')
              if (existing) return prev.map((m) => m.id === 'streaming' ? { ...m, content: ansAcc } : m)
              return [...prev, { role: 'bot', content: ansAcc, id: 'streaming', streaming: true }]
            })
          }, 15)
          return
        }
        const chunk = mockThink.slice(thinkIdx, thinkIdx + 8)
        thinkAcc += chunk
        thinkIdx += 8
        setThinkText(thinkAcc)
      }, 20)
      return
    }

    // Live mode: POST request with SSE streaming
    const formData = new FormData()
    formData.append('image', imageFile)
    formData.append('question', userMsg)
    formData.append('image_type', imageType)
    formData.append('token', token)
    if (patientId) {
      formData.append('patient_id', patientId)
    }

    try {
      const response = await fetch(`${BASE_URL}/api/chat/analyze-image`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `Upload failed: ${response.statusText}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let botAcc = ''
      let thinkAcc = ''
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue

          try {
            const dataStr = trimmed.slice(6)
            const msg = JSON.parse(dataStr)

            if (msg.type === 'think_start') {
              setIsThinking(true)
              setThinkText('')
              setThinkDone(null)
              thinkAcc = ''
            }
            if (msg.type === 'think') {
              thinkAcc += msg.chunk
              setThinkText(thinkAcc)
            }
            if (msg.type === 'think_done') {
              setIsThinking(false)
              setThinkDone({ text: thinkAcc, duration: msg.duration })
            }
            if (msg.type === 'chunk') {
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
              setIsImageAnalyzing(false)
              setIsThinking(false)   // clear any thinking that may have started
              addMessage({ role: 'bot', content: botAcc, id: Date.now() })
              setMessages((prev) => prev.filter((m) => m.id !== 'streaming'))
            }
            if (msg.type === 'error') {
              addMessage({ role: 'bot', content: `⚠️ ${msg.message}`, id: Date.now(), isError: true })
              setIsStreaming(false)
              setIsThinking(false)
              setIsImageAnalyzing(false)
            }
          } catch (e) {
            // Ignore parse errors on half-read lines
          }
        }
      }
    } catch (err) {
      const message = err?.message === 'Failed to fetch'
        ? `API unreachable at ${BASE_URL}. Make sure the FastAPI backend is running on port 8000, then retry the image upload.`
        : err.message
      addMessage({ role: 'bot', content: `⚠️ Connection error: ${message}`, id: Date.now(), isError: true })
      setIsStreaming(false)
      setIsThinking(false)
      setIsImageAnalyzing(false)
    }
  }, [token, addMessage])

  /**
   * Dispatch a user message to the appropriate streaming handler.
   * No-ops if a stream is already in progress or both `userMsg` and
   * `imageFile` are empty.
   *
   * @param {string} userMsg                   - The user's text input.
   * @param {number|string|null} patientId      - The active patient's ID.
   * @param {'patient'|'general'} [mode='patient'] - Context mode for the AI backend.
   * @param {File|null} [imageFile=null]         - Optional image file to analyse.
   * @param {string} [imageType='general']       - Image category label forwarded to the backend.
   */
  const sendMessage = useCallback((userMsg, patientId, mode = 'patient', imageFile = null, imageType = 'general') => {
    if ((!userMsg.trim() && !imageFile) || isStreaming || isThinking) return
    if (imageFile) {
      _imageStream(imageFile, imageType, userMsg, patientId, mode)
    } else {
      if (IS_MOCK) _mockStream(userMsg, patientId, mode)
      else         _liveStream(userMsg, patientId, mode)
    }
  }, [isStreaming, isThinking, _mockStream, _liveStream, _imageStream])

  /**
   * Clear the conversation history and reset all streaming/thinking state.
   * Typically called when the user switches to a different patient context.
   */
  const clearMessages = useCallback(() => {
    setMessages([])
    setIsThinking(false)
    setThinkText('')
    setThinkDone(null)
    setIsStreaming(false)
    setIsImageAnalyzing(false)
  }, [])

  return { messages, isThinking, thinkText, thinkDone, isStreaming, isImageAnalyzing, sendMessage, clearMessages }
}
