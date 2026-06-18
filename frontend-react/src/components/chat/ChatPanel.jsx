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

export default function ChatPanel({ patient, mode: initialMode = 'patient' }) {
  const [mode, setMode] = useState(initialMode)
  const [input, setInput] = useState('')
  const [thinkExpanded, setThinkExpanded] = useState(false)
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)

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

  const handleSend = () => {
    if (!input.trim()) return
    sendMessage(input, patient?.id, mode)
    setInput('')
    textareaRef.current?.focus()
  }

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
        <div className="flex items-end gap-2">
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
            disabled={!input.trim() || isStreaming || isThinking}
            loading={isStreaming || isThinking}
            size="icon"
            className="mb-0.5"
            aria-label="Send message"
          >
            <Send size={16} />
          </Button>
        </div>
      </div>
    </div>
  )
}

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
