import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { ScrollArea } from '../common/ScrollArea'
import { ChatComposer } from './ChatComposer'
import { ChatMessageBubble } from './ChatMessageBubble'

const POLL_MS = 3000
const BOTTOM_THRESHOLD_PX = 80

export function ChatThread({ sessionId, focusedArtifact, onClearFocus }) {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const bottomRef = useRef(null)
  const scrollRef = useRef(null)
  // Whether the view was at (or near) the bottom before this messages update —
  // polling refetches every 3s regardless of scroll position, so without this
  // it would yank the user back to the bottom mid-read every tick.
  const stickToBottomRef = useRef(true)

  useEffect(() => {
    let mounted = true

    async function loadMessages() {
      try {
        const result = await api.getChatMessages(sessionId)
        if (mounted) setMessages(result.messages || [])
      } catch (error) {
        console.error('Failed to load chat messages:', error)
      }
    }

    loadMessages()
    const timer = window.setInterval(loadMessages, POLL_MS)
    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [sessionId])

  useEffect(() => {
    if (!stickToBottomRef.current) return
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    stickToBottomRef.current = distanceFromBottom < BOTTOM_THRESHOLD_PX
  }

  const handleToggleStar = async (messageId, nextStarred) => {
    // Optimistic — starring should feel instant, and it's low-stakes to revert.
    setMessages((prev) =>
      prev.map((msg) => (msg.message_id === messageId ? { ...msg, starred: nextStarred } : msg)),
    )
    try {
      await api.starMessage(sessionId, messageId, nextStarred)
    } catch (error) {
      console.error('Failed to star message:', error)
      setMessages((prev) =>
        prev.map((msg) =>
          msg.message_id === messageId ? { ...msg, starred: !nextStarred } : msg,
        ),
      )
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!input.trim() || isLoading) return

    setIsLoading(true)
    const text = input
    const artifactId = focusedArtifact?.artifact_id ?? null
    setInput('')
    onClearFocus?.() // one-shot scoping — the next message goes back to general chat

    // Sending a message always scrolls to it, even if the user had scrolled
    // up to read earlier history.
    stickToBottomRef.current = true

    const tempMessage = {
      message_id: `temp-${Date.now()}`,
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, tempMessage])

    try {
      await api.sendChatMessage(sessionId, text, artifactId)
      const result = await api.getChatMessages(sessionId)
      setMessages(result.messages || [])
    } catch (error) {
      console.error('Error sending message:', error)
      alert(`Failed to send message: ${error.message}`)
      setMessages((prev) => prev.filter((msg) => !msg.message_id.startsWith('temp-')))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="chat-thread">
      <ScrollArea className="chat-scroll" innerRef={scrollRef} onScroll={handleScroll}>
        <div className="chat-messages-list">
          {messages.length === 0 && !isLoading && (
            <div className="chat-welcome">
              <h3>Hi, I&apos;m Planner.</h3>
              <p>Tell me about the pipeline you want to build.</p>
            </div>
          )}
          {messages.map((msg) => (
            <ChatMessageBubble
              key={msg.message_id}
              messageId={msg.message_id}
              role={msg.role}
              content={msg.content}
              starred={msg.starred}
              artifactName={msg.metadata?.artifact_name}
              onToggleStar={msg.message_id.startsWith('temp-') ? undefined : handleToggleStar}
            />
          ))}
          {isLoading && <ChatMessageBubble role="assistant" content="Thinking…" />}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
      {focusedArtifact && (
        <div className="chat-focus-chip">
          <span>Re: {focusedArtifact.name}</span>
          <button type="button" onClick={onClearFocus} aria-label="Clear scoped artifact">
            ✕
          </button>
        </div>
      )}
      <ChatComposer value={input} onChange={setInput} onSubmit={handleSubmit} disabled={isLoading} />
    </div>
  )
}
