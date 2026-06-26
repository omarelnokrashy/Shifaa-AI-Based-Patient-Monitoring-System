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
import { Send, ImagePlus, Brain, ChevronDown, ChevronUp, Loader2, X, ScanSearch } from 'lucide-react'
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
export default function ChatPanel({ patient }) {
  const mode = patient ? 'patient' : 'general'
  const [input, setInput] = useState('')
  const [thinkExpanded, setThinkExpanded] = useState(false)
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const [selectedFile, setSelectedFile] = useState(null)
  const [imageType, setImageType] = useState('general')
  const fileInputRef = useRef(null)

  const {
    messages, isThinking, thinkText, thinkDone, isStreaming, isImageAnalyzing,
    sendMessage, clearMessages,
  } = useChatStream(patient?.id, mode)

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
        <div className="flex items-center gap-2">
          <Brain size={18} className="text-teal-600 shrink-0" />
          <span className="font-semibold text-navy-900">
            {patient ? `Specialized Chat — ${patient.name}` : 'Global Medical Q&A'}
          </span>
        </div>
        {patient && (
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

        {/* Image analyzing indicator — shown while waiting for MedGemma vision response */}
        {isImageAnalyzing && (
          <div className="flex items-center gap-2 px-3 py-2 bg-teal-50 border border-teal-200 rounded-xl text-teal-700 text-xs font-medium">
            <ScanSearch size={14} className="animate-pulse shrink-0" />
            <span>Analyzing image with MedGemma 1.5…</span>
          </div>
        )}

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
          <div className="mb-2 px-3 py-2 bg-teal-50/60 border border-teal-200 rounded-xl flex items-center gap-3">
            <div className="relative w-14 h-14 rounded-lg overflow-hidden border border-teal-300 bg-white shrink-0 shadow-sm">
              <img
                src={URL.createObjectURL(selectedFile)}
                alt="Preview"
                className="w-full h-full object-cover"
              />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className="text-[9px] font-bold uppercase tracking-wider text-teal-600 bg-teal-100 px-1.5 py-0.5 rounded">
                  MedGemma 1.5
                </span>
              </div>
              <p className="text-xs font-medium text-navy-800 truncate">{selectedFile.name}</p>
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
            <button
              type="button"
              onClick={() => { setSelectedFile(null); if (fileInputRef.current) fileInputRef.current.value = '' }}
              className="p-1.5 text-navy-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0"
              title="Remove image"
            >
              <X size={14} />
            </button>
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
          disabled={isStreaming || isThinking || isImageAnalyzing}
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
              selectedFile
                ? 'Add a question about this image… or press Send to analyze'
                : mode === 'patient' && patient
                ? `Ask about ${patient.name}… (Enter to send)`
                : 'Ask a general medical question… (Enter to send)'
            }
            className="flex-1 resize-none px-3 py-2 text-sm bg-navy-50 border border-navy-200 rounded-lg
                       text-navy-900 placeholder-navy-400 focus:outline-none focus:ring-2 focus:ring-teal-500
                       focus:border-teal-500 transition-colors"
            disabled={isStreaming || isThinking || isImageAnalyzing}
          />
          <Button
            onClick={handleSend}
            disabled={(!input.trim() && !selectedFile) || isStreaming || isThinking || isImageAnalyzing}
            loading={isStreaming || isThinking || isImageAnalyzing}
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
          <div className="mb-2">
            <div className="max-w-[220px] rounded-xl overflow-hidden border border-navy-500/30 bg-white shadow-sm">
              <img src={msg.image} alt="Uploaded medical image" className="w-full h-auto max-h-[180px] object-contain" />
            </div>
            <div className="mt-1 flex items-center gap-1 text-[10px] text-navy-300">
              <ScanSearch size={10} />
              <span>Sent to MedGemma 1.5</span>
            </div>
          </div>
        )}
        {isUser ? (
          <p className="whitespace-pre-wrap">{msg.content || <span className="italic text-navy-300">[Image attached]</span>}</p>
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
