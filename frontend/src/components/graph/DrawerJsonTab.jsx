import { useState } from 'react'

export function DrawerJsonTab({ data }) {
  const [copied, setCopied] = useState(false)
  const json = JSON.stringify(data, null, 2)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(json)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch (error) {
      console.error('Copy failed:', error)
    }
  }

  return (
    <div>
      <div className="code-well-header">
        <span className="code-well-label">task.json</span>
        <button type="button" className="copy-btn raised-sm" onClick={copy}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
            <rect x="9" y="9" width="11" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
            <path d="M5 15V5a1 1 0 0 1 1-1h10" stroke="currentColor" strokeWidth="1.6" />
          </svg>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="code-well pressed">{json}</pre>
    </div>
  )
}
