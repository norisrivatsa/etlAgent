import { useEffect, useRef, useState } from 'react'
import './popover.css'

/**
 * Click-to-open, click-away-to-close popover. `trigger` is a render prop so
 * the caller controls the trigger button's own look; `children` may also be
 * a render prop (receiving `close`) when panel content needs to dismiss
 * itself, e.g. a menu item selection.
 */
export function Popover({ trigger, children, align = 'right', panelClassName = '' }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    function handleClickAway(event) {
      if (rootRef.current && !rootRef.current.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickAway)
    return () => document.removeEventListener('mousedown', handleClickAway)
  }, [open])

  const close = () => setOpen(false)

  return (
    <div className="popover-root" ref={rootRef}>
      {trigger({ open, toggle: () => setOpen((v) => !v), close })}
      {open && (
        <div className={`popover-panel raised ${align} ${panelClassName}`}>
          {typeof children === 'function' ? children({ close }) : children}
        </div>
      )}
    </div>
  )
}
