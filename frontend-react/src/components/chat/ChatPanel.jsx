/**
 * ChatPanel — the streaming clinical chatbot interface.
 *
 * Features:
 * - Mode switch: Patient Q&A (uses patient context) / General Q&A
 * - Token-by-token streaming via useChatStream hook
 * - Collapsible reasoning block: auto-expands while thinking, auto-collapses
 *   with "Thought for X.Xs" label once done
 * - Markdown rendering for bot messages (react-markdown + remark-gfm)
 * - Image upload modal trigger for X-ray/CT/lab report analysis
 * - Auto-scroll to latest message
 */
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Send, ImagePlus, Brain, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { useChatStream } from '../../hooks/useChatStream'
import Button from '../ui/Button'

/**
 * The primary chat interface for clinical Q&A.
 *
 * @param {Object} props
 * @param {Object|null} [props.patient]          The currently selected patient object (id, name, etc.).
 *                                               When provided, Patient Q&A mode uses their medical context.
 * @param {'patient'|'general'} [props.mode='patient'] Initial chat mode.
 *   - `'patient'`  — sends patient context alongside the query.
 *   - `'general'`  — general medical Q&A without patient context.
 * @returns {JSX.Element}
 */
export default function ChatPanel({ patient, mode: initialMode = 'patient' }) {
  const [mode, setMode] = useState(initialMode)
  const [input, setInput] = useState('')
  const [thinkExpanded, setThinkExpanded] = useState(false)
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const [selectedFile, setSelectedFile] = useState(null)
  const [imageType, setImageType] = useState('general')
  const fileInputRef = useRef(null)

  const {
    messages, isThinking, thinkText, thinkDone, isStreaming,
    sendMessage, clearMessages,
  } = useChatStream()

  // Auto-expand reasoning while thinking, auto-collapse once done
  useEffect(() => { if (isThinking) setThinkExpanded(true)  }, [isThinking])
  useEffect(() => { if (thinkDone)  setThinkExpanded(false) }, [thinkDone])

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isThinking, thinkText])

  /**
   * Handles file selection from the hidden file input.
   * Auto-detects the medical image type from the filename and updates `imageType` state.
   *
   * @param {React.ChangeEvent<HTMLInputElement>} e - The input change event.
   * @returns {void}
   */
  const handleFileChange = (e) => {
    const file = e.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      const name = file.name.toLowerCase()
      if (name.includes('xray') || name.includes('x-ray')) setImageType('xray')
      else if (name.includes('ct') || name.includes('mri')) setImageType('ct_mri')
      else if (name.includes('lab') || name.includes('report')) setImageType('lab_report')
      else if (name.includes('dermo') || name.includes('skin')) setImageType('dermatology')
      else if (name.includes('note') || name.includes('handwritten')) setImageType('handwritten')
      else setImageType('general')
    }
  }

  /**
   * Dispatches the current input text and/or selected file to the chat stream.
   * Resets the textarea and clears the selected file after sending.
   * No-ops if both the text input is empty and no file is attached.
   *
   * @returns {void}
   */
  const handleSend = () => {
    if (!input.trim() && !selectedFile) return
    sendMessage(input, patient?.id, mode, selectedFile, imageType)
    setInput('')
    setSelectedFile(null)
    textareaRef.current?.focus()
  }

  /**
   * Keyboard handler for the textarea. Submits the message on Enter (without Shift).
   * Shift+Enter inserts a newline as normal.
   *
   * @param {React.KeyboardEvent<HTMLTextAreaElement>} e - The keyboard event.
   * @returns {void}
   */
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  return (
    <div className="flex flex-col h-full bg-navy-50 rounded-xl overflow-hidden border border-navy-100">

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-3 bg-white border-b border-navy-100">
        <div className="flex items-center gap-1 bg-navy-100 rounded-lg p-1">
          {['patient', 'general'].map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); clearMessages() }}
              className={clsx(
                'px-3 py-1.5 rounded-md text-sm font-medium transition-all',
                mode === m
                  ? 'bg-white text-navy-900 shadow-sm'
                  : 'text-navy-500 hover:text-navy-700',
              )}
            >
              {m === 'patient' ? (patient ? `${patient.name.split(' ')[0]} Q&A` : 'Patient Q&A') : 'General Q&A'}
            </button>
          ))}
        </div>
        {mode === 'patient' && patient && (
          <span className="text-xs text-navy-400 font-mono">
            ID #{patient.id}
          </span>
        )}
      </div>

      {/* ── Messages ────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && !isThinking && (
          <div className="flex flex-col items-center justify-center h-full text-center py-12">
            <Brain size={36} className="text-navy-300 mb-3" />
            <p className="text-navy-400 font-medium text-sm">
              {mode === 'patient' && patient
                ? `Ask me anything about ${patient.name}'s history.`
                : 'Ask a general medical question.'}
            </p>
            {mode === 'patient' && patient && (
              <p className="text-navy-300 text-xs mt-1">
                I have access to diagnoses, medications, labs, and visit notes.
              </p>
            )}
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}

        {/* Reasoning block (while thinking or after thought) */}
        {(isThinking || thinkDone) && (
          <div className="think-block">
            <button
              onClick={() => setThinkExpanded((e) => !e)}
              className="flex items-center gap-2 w-full text-left text-teal-700 font-sans font-medium"
            >
              {isThinking ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  <span className="text-sm">Thinking…</span>
                </>
              ) : (
                <>
                  <Brain size={14} />
                  <span className="text-sm">Thought for {thinkDone?.duration}s</span>
                </>
              )}
              <span className="ml-auto">
                {thinkExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </span>
            </button>
            {thinkExpanded && (
              <p className="mt-2 text-navy-500 text-xs leading-relaxed whitespace-pre-wrap font-mono">
                {isThinking ? thinkText : thinkDone?.text}
                {isThinking && <span className="animate-pulse">▊</span>}
              </p>
            )}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ───────────────────────────────────────────────────── */}
      <div className="border-t border-navy-100 bg-white p-3">
        {/* Image Preview Block */}
        {selectedFile && (
          <div className="mb-2 px-3 py-2 bg-navy-50/50 border border-navy-100 rounded-lg flex items-center gap-3">
            <div className="relative w-12 h-12 rounded-lg overflow-hidden border border-navy-200 bg-white shrink-0">
              <img
                src={URL.createObjectURL(selectedFile)}
                alt="Preview"
                className="w-full h-full object-cover"
              />
              <button
                type="button"
                onClick={() => setSelectedFile(null)}
                className="absolute top-0 right-0 p-0.5 bg-red-500 text-white rounded-bl hover:bg-red-600 transition-colors"
              >
                <span className="block text-[8px] font-bold leading-none">X</span>
              </button>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-navy-700 truncate">{selectedFile.name}</p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-[10px] text-navy-400">Scan type:</span>
                <select
                  value={imageType}
                  onChange={(e) => setImageType(e.target.value)}
                  className="text-[10px] font-medium text-teal-700 bg-transparent border-none p-0 focus:ring-0 cursor-pointer"
                >
                  <option value="general">General Scan</option>
                  <option value="xray">Chest X-Ray</option>
                  <option value="ct_mri">CT / MRI Scan</option>
                  <option value="lab_report">Lab Report</option>
                  <option value="dermatology">Dermatology Image</option>
                  <option value="handwritten">Handwritten Notes</option>
                </select>
              </div>
            </div>
          </div>
        )}

        <div className="flex items-end gap-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept="image/*"
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="p-2 text-navy-400 hover:text-teal-600 hover:bg-navy-50 rounded-lg transition-colors mb-0.5 shrink-0"
            title="Upload medical image"
            disabled={isStreaming || isThinking}
          >
            <ImagePlus size={20} />
          </button>
          <textarea
            ref={textareaRef}
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              mode === 'patient' && patient
                ? `Ask about ${patient.name}… (Enter to send)`
                : 'Ask a general medical question… (Enter to send)'
            }
            className="flex-1 resize-none px-3 py-2 text-sm bg-navy-50 border border-navy-200 rounded-lg
                       text-navy-900 placeholder-navy-400 focus:outline-none focus:ring-2 focus:ring-teal-500
                       focus:border-teal-500 transition-colors"
            disabled={isStreaming || isThinking}
          />
          <Button
            onClick={handleSend}
            disabled={(!input.trim() && !selectedFile) || isStreaming || isThinking}
            loading={isStreaming || isThinking}
            size="icon"
            className="mb-0.5 shrink-0"
            aria-label="Send message"
          >
            <Send size={16} />
          </Button>
        </div>
      </div>
    </div>
  )
}

/**
 * Renders a single chat message bubble, styled differently for user and assistant roles.
 * Bot messages are rendered as Markdown; user messages are rendered as plain pre-wrapped text.
 * Supports inline image attachments for user messages and a streaming cursor animation.
 *
 * @param {Object} props
 * @param {Object} props.msg              The message object from the chat stream.
 * @param {string} props.msg.id           Unique message identifier.
 * @param {'user'|'assistant'} props.msg.role  Determines bubble alignment and styling.
 * @param {string} props.msg.content      Message text content (Markdown for assistant).
 * @param {string} [props.msg.image]      Base64 or object-URL of an attached image (user messages only).
 * @param {boolean} [props.msg.isError]   When true, applies error (red) styling.
 * @param {boolean} [props.msg.streaming] When true, renders an animated cursor at the end.
 * @returns {JSX.Element}
 */
function MessageBubble({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={clsx('flex', isUser ? 'justify-end' : 'justify-start')}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-teal-600 flex items-center justify-center shrink-0 mr-2 mt-0.5">
          <Brain size={13} className="text-white" />
        </div>
      )}
      <div
        className={clsx(
          'max-w-[78%] px-4 py-3 text-sm leading-relaxed',
          isUser ? 'bubble-user' : 'bubble-bot',
          msg.isError && 'border-red-200 bg-red-50 text-red-800',
          msg.streaming && 'border-teal-200',
        )}
      >
        {isUser && msg.image && (
          <div className="mb-2 max-w-[200px] rounded-lg overflow-hidden border border-navy-600 bg-white">
            <img src={msg.image} alt="Uploaded attachment" className="w-full h-auto max-h-[150px] object-contain" />
          </div>
        )}
        {isUser ? (
          <p className="whitespace-pre-wrap">{msg.content}</p>
        ) : (
          <div className="prose prose-sm prose-navy max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            {msg.streaming && <span className="text-teal-500 animate-pulse ml-1">▊</span>}
          </div>
        )}
      </div>
    </div>
  )
}
