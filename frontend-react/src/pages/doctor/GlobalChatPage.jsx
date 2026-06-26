import ChatPanel from '../../components/chat/ChatPanel'

/**
 * Global Chat Page — open-ended general medical Q&A without patient context.
 *
 * Renders the ChatPanel component in its general mode by omitting the `patient` prop.
 *
 * @returns {JSX.Element}
 */
export default function GlobalChatPage() {
  return (
    <div className="space-y-5 max-w-5xl mx-auto">
      <div>
        <h1 className="font-heading font-bold text-2xl text-navy-900">Global Chat</h1>
        <p className="text-navy-400 text-sm mt-0.5">General medical Q&A and verification of guidelines</p>
      </div>
      <div className="h-[calc(100vh-14rem)] min-h-[500px]">
        <ChatPanel />
      </div>
    </div>
  )
}
