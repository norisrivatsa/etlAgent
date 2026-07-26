function StarIcon({ filled }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'}>
      <path
        d="M12 3.5l2.6 5.4 5.9.8-4.3 4.2 1 5.9L12 16.9l-5.2 2.9 1-5.9-4.3-4.2 5.9-.8L12 3.5Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function ChatMessageBubble({ messageId, role, content, starred, artifactName, onToggleStar }) {
  const mine = role === 'user'
  return (
    <div className={`chat-row${mine ? ' mine' : ''}`}>
      <div className={`chat-bubble-group${mine ? ' mine' : ''}`}>
        <div className={`chat-bubble raised-sm${mine ? ' mine' : ''}`}>
          {artifactName && <div className="chat-bubble-artifact-tag">Re: {artifactName}</div>}
          {content}
        </div>
        {messageId && onToggleStar && (
          <button
            type="button"
            className={`chat-star-btn${starred ? ' starred' : ''}`}
            onClick={() => onToggleStar(messageId, !starred)}
            aria-label={starred ? 'Unstar message' : 'Star message'}
            title={starred ? 'Unstar — remove from Planner’s permanent context' : 'Star — always keep in Planner’s context'}
          >
            <StarIcon filled={starred} />
          </button>
        )}
      </div>
    </div>
  )
}
