export function ChatComposer({ value, onChange, onSubmit, disabled }) {
  return (
    <form className="chat-composer raised" onSubmit={onSubmit}>
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Message Planner…"
        className="chat-composer-input pressed"
        disabled={disabled}
      />
      <button type="submit" className="chat-send-btn" disabled={!value.trim() || disabled}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path
            d="M4 12h15M13 6l6 6-6 6"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </form>
  )
}
