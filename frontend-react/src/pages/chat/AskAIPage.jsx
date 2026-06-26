/**
 * AskAIPage — the dedicated clinical AI chat workspace.
 *
 * Layout:
 *   ┌──────────────┬─────────────────────────────────────┐
 *   │  History rail │  ChatPanel (mode toggle + picker +  │
 *   │  (saved chats)│  streaming conversation)            │
 *   └──────────────┴─────────────────────────────────────┘
 *
 * - The left rail lists this user's saved conversations (persisted to
 *   localStorage via `chatStore`). Click to resume, hover to delete.
 * - "New Chat" starts a fresh thread; switching mode or patient also starts a
 *   new thread so each saved conversation has a single, consistent context.
 * - Deep-link support: `/<role>/chat?patient=<id>` opens a fresh Patient Q&A
 *   thread pre-loaded with that patient (used by the patient detail "Ask"
 *   button).
 *
 * This page is UI-only — it reuses the existing streaming hook and patient API
 * without changing any backend behaviour.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Plus, Trash2, MessageSquare, Sparkles, User, Stethoscope } from 'lucide-react'
import ChatPanel from '../../components/chat/ChatPanel'
import { apiGetPatients, apiGetPatient } from '../../api/client'
import { formatDistanceToNow } from '../../components/utils/time'
import useAuthStore from '../../store/authStore'
import useChatStore from '../../store/chatStore'
import { clsx } from 'clsx'

/** Generate a stable client-side session id. */
const freshId = () =>
  (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `c_${Date.now()}_${Math.random().toString(36).slice(2)}`

/**
 * The "Ask AI" page component.
 *
 * @returns {JSX.Element}
 */
export default function AskAIPage() {
  const user = useAuthStore((s) => s.user)

  // Chat-history store
  const allSessions       = useChatStore((s) => s.sessions)
  const upsertSession     = useChatStore((s) => s.upsertSession)
  const deleteSession     = useChatStore((s) => s.deleteSession)
  const renameSession     = useChatStore((s) => s.renameSession)
  const clearUserSessions = useChatStore((s) => s.clearUserSessions)

  const sessions = useMemo(
    () =>
      allSessions
        .filter((s) => String(s.userId) === String(user?.id))
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    [allSessions, user?.id],
  )

  // Active-conversation context
  const [patients, setPatients] = useState([])
  const [activeId, setActiveId] = useState(() => freshId())
  const [mode, setMode]         = useState('patient')
  const [patient, setPatient]   = useState(null)

  const [searchParams, setSearchParams] = useSearchParams()
  const [confirmClear, setConfirmClear] = useState(false)
  const deepLinkApplied = useRef(false)

  // Load the patient list for the in-chat picker.
  useEffect(() => {
    apiGetPatients('').then(setPatients).catch(() => setPatients([]))
  }, [])

  // Deep link: open a fresh Patient Q&A thread for ?patient=<id>.
  useEffect(() => {
    const pid = searchParams.get('patient')
    if (!pid || deepLinkApplied.current) return
    deepLinkApplied.current = true
    apiGetPatient(pid).then((p) => {
      if (p) {
        setPatient(p)
        setMode('patient')
        setActiveId(freshId())
      }
      // Strip the param so a manual refresh doesn't keep re-opening it.
      const next = new URLSearchParams(searchParams)
      next.delete('patient')
      setSearchParams(next, { replace: true })
    })
  }, [searchParams, setSearchParams])

  const activeSession  = sessions.find((s) => s.id === activeId) || null
  const activeMessages = activeSession?.messages || []

  /** Start a brand-new conversation, keeping the current mode/patient context. */
  const newChat = useCallback(() => setActiveId(freshId()), [])

  /** Toggle Patient/General mode — starts a new thread for the new context. */
  const handleModeChange = useCallback((m) => {
    setMode(m)
    setActiveId(freshId())
  }, [])

  /** Pick a patient — switches to Patient Q&A and starts a new thread. */
  const handleSelectPatient = useCallback((p) => {
    setPatient(p)
    setMode('patient')
    setActiveId(freshId())
  }, [])

  /** Resume a saved conversation from the history rail. */
  const loadSession = useCallback((s) => {
    setActiveId(s.id)
    setMode(s.mode)
    setPatient(s.patientId ? { id: s.patientId, name: s.patientName } : null)
  }, [])

  /** Persist the settled conversation snapshot to history. */
  const handlePersist = useCallback(
    (messages) => {
      // Drop transient object-URL images — they don't survive a reload, so
      // storing them would render as broken images when the chat is reopened.
      const snapshot = messages.map((m) =>
        typeof m.image === 'string' && m.image.startsWith('blob:') ? { ...m, image: undefined } : m,
      )
      upsertSession({
        id: activeId,
        userId: user?.id,
        mode,
        patientId: mode === 'patient' ? (patient?.id ?? null) : null,
        patientName: mode === 'patient' ? (patient?.name ?? null) : null,
        messages: snapshot,
      })
    },
    [upsertSession, activeId, user?.id, mode, patient],
  )

  /** Delete a saved session; if it's the active one, drop into a fresh thread. */
  const handleDelete = useCallback(
    (e, id) => {
      e.stopPropagation()
      deleteSession(id)
      if (id === activeId) setActiveId(freshId())
    },
    [deleteSession, activeId],
  )

  /** Rename a saved session (falls back to ignoring empty titles). */
  const handleRename = useCallback(
    (id, title) => {
      const trimmed = title.trim()
      if (trimmed) renameSession(id, trimmed)
    },
    [renameSession],
  )

  /** Wipe every saved conversation for this user and start fresh. */
  const handleClearAll = useCallback(() => {
    clearUserSessions(user?.id)
    setConfirmClear(false)
    setActiveId(freshId())
  }, [clearUserSessions, user?.id])

  return (
    <div className="max-w-6xl mx-auto flex flex-col h-[calc(100vh-7rem)]">
      {/* Page heading */}
      <div className="flex items-center gap-2.5 mb-4 shrink-0">
        <span className="p-2 rounded-lg bg-teal-50 text-teal-600">
          <Sparkles size={18} />
        </span>
        <div>
          <h1 className="font-heading font-bold text-2xl text-navy-900 leading-tight">Ask AI</h1>
          <p className="text-navy-400 text-sm">Clinical Q&amp;A assistant · your conversations are saved</p>
        </div>
      </div>

      <div className="flex gap-4 flex-1 min-h-0">
        {/* ── History rail ──────────────────────────────────────────────── */}
        <aside className="card p-0 w-64 shrink-0 flex flex-col overflow-hidden">
          <div className="p-3 border-b border-navy-100">
            <button
              onClick={newChat}
              className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg
                         bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 transition-colors"
            >
              <Plus size={15} /> New Chat
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {sessions.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-center h-full px-3 py-10">
                <MessageSquare size={28} className="text-navy-200 mb-2" />
                <p className="text-navy-400 text-xs">No saved chats yet.</p>
                <p className="text-navy-300 text-xs mt-0.5">Start a conversation to see it here.</p>
              </div>
            ) : (
              sessions.map((s) => (
                <SessionRow
                  key={s.id}
                  session={s}
                  active={s.id === activeId}
                  onClick={() => loadSession(s)}
                  onDelete={(e) => handleDelete(e, s.id)}
                  onRename={(title) => handleRename(s.id, title)}
                />
              ))
            )}
          </div>

          {/* Clear-all footer (destructive — two-step confirm) */}
          {sessions.length > 0 && (
            <div className="p-2 border-t border-navy-100">
              {confirmClear ? (
                <div className="flex items-center gap-1.5">
                  <span className="flex-1 text-xs text-navy-500 px-1">Delete all {sessions.length}?</span>
                  <button
                    onClick={handleClearAll}
                    className="px-2.5 py-1 rounded-md bg-red-600 text-white text-xs font-medium hover:bg-red-700 transition-colors"
                  >
                    Clear
                  </button>
                  <button
                    onClick={() => setConfirmClear(false)}
                    className="px-2.5 py-1 rounded-md text-navy-500 text-xs font-medium hover:bg-navy-100 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmClear(true)}
                  className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg
                             text-navy-500 hover:text-red-600 hover:bg-red-50 text-xs font-medium transition-colors"
                >
                  <Trash2 size={13} /> Clear all history
                </button>
              )}
            </div>
          )}
        </aside>

        {/* ── Chat panel ────────────────────────────────────────────────── */}
        <div className="flex-1 min-w-0">
          <ChatPanel
            key={activeId}
            patient={patient}
            patients={patients}
            mode={mode}
            onModeChange={handleModeChange}
            onSelectPatient={handleSelectPatient}
            initialMessages={activeMessages}
            onPersist={handlePersist}
          />
        </div>
      </div>
    </div>
  )
}

/**
 * A single row in the chat-history rail. Double-click the title to rename.
 *
 * @param {object}   props
 * @param {object}   props.session  - The saved session.
 * @param {boolean}  props.active   - Whether this is the currently open session.
 * @param {Function} props.onClick  - Resume handler.
 * @param {Function} props.onDelete - Delete handler (receives the click event).
 * @param {Function} props.onRename - Rename handler (receives the new title string).
 * @returns {JSX.Element}
 */
function SessionRow({ session, active, onClick, onDelete, onRename }) {
  const isPatient = session.mode === 'patient' && session.patientName
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(session.title)

  /** Enter rename mode, seeded with the current title. */
  const startEdit = (e) => {
    e.stopPropagation()
    setDraft(session.title)
    setEditing(true)
  }

  /** Commit the edited title and leave rename mode. */
  const commit = () => {
    setEditing(false)
    if (draft.trim() && draft.trim() !== session.title) onRename(draft)
  }

  /** Keyboard handling within the rename input: Enter commits, Escape cancels. */
  const onKeyDown = (e) => {
    e.stopPropagation()
    if (e.key === 'Enter') { e.preventDefault(); commit() }
    else if (e.key === 'Escape') { e.preventDefault(); setEditing(false) }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => !editing && onClick()}
      onKeyDown={(e) => { if (!editing && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onClick() } }}
      className={clsx(
        'group w-full text-left px-3 py-2.5 rounded-lg transition-colors cursor-pointer',
        active ? 'bg-teal-50 border border-teal-200' : 'hover:bg-navy-50 border border-transparent',
      )}
    >
      <div className="flex items-start gap-2">
        <span className={clsx('mt-0.5 shrink-0', active ? 'text-teal-600' : 'text-navy-300')}>
          {isPatient ? <Stethoscope size={14} /> : <MessageSquare size={14} />}
        </span>
        <div className="min-w-0 flex-1">
          {editing ? (
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              onKeyDown={onKeyDown}
              onBlur={commit}
              onFocus={(e) => e.target.select()}
              className="w-full text-sm font-medium bg-white border border-teal-300 rounded px-1.5 py-0.5
                         text-navy-900 focus:outline-none focus:ring-2 focus:ring-teal-500"
            />
          ) : (
            <p
              onDoubleClick={startEdit}
              title="Double-click to rename"
              className={clsx('text-sm font-medium truncate', active ? 'text-teal-900' : 'text-navy-800')}
            >
              {session.title}
            </p>
          )}
          <div className="flex items-center gap-1.5 mt-0.5">
            <span
              className={clsx(
                'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium truncate max-w-[110px]',
                isPatient ? 'bg-teal-100 text-teal-700' : 'bg-navy-100 text-navy-600',
              )}
            >
              {isPatient ? <User size={9} /> : null}
              {isPatient ? session.patientName : 'General'}
            </span>
            <span className="text-[10px] text-navy-400 shrink-0">
              {formatDistanceToNow(session.updatedAt)}
            </span>
          </div>
        </div>
        <span
          role="button"
          tabIndex={-1}
          onClick={onDelete}
          className="shrink-0 p-1 rounded text-navy-300 opacity-0 group-hover:opacity-100
                     hover:text-red-600 hover:bg-red-50 transition-all"
          title="Delete chat"
        >
          <Trash2 size={13} />
        </span>
      </div>
    </div>
  )
}
