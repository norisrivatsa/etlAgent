import { useCallback, useEffect, useRef, useState } from 'react'
import './scrollArea.css'

const MIN_THUMB_PX = 24

/**
 * Custom overlay scrollbar matching the app's neomorphic accent palette.
 * Wraps native overflow scrolling (wheel/touch/keyboard/scrollIntoView all
 * keep working exactly as before) and draws its own thumb(s) on top, since
 * there's no cross-browser way to fully restyle the native scrollbar to
 * match brand colors. Used wherever content scrolls: chat, session
 * switcher, node drawers, the graph canvas.
 */
export function ScrollArea({ className = '', innerRef, onScroll, children }) {
  const viewportRef = useRef(null)
  const [metrics, setMetrics] = useState({ y: null, x: null })
  const [dragging, setDragging] = useState(null) // 'x' | 'y' | null

  const setViewport = useCallback(
    (node) => {
      viewportRef.current = node
      if (innerRef) innerRef.current = node
    },
    [innerRef],
  )

  const measure = useCallback(() => {
    const el = viewportRef.current
    if (!el) return
    const { scrollTop, scrollHeight, clientHeight, scrollLeft, scrollWidth, clientWidth } = el

    let y = null
    if (scrollHeight > clientHeight + 1) {
      const size = Math.max((clientHeight / scrollHeight) * clientHeight, MIN_THUMB_PX)
      const range = clientHeight - size
      const offset = (scrollTop / (scrollHeight - clientHeight)) * range
      y = { size, offset }
    }

    let x = null
    if (scrollWidth > clientWidth + 1) {
      const size = Math.max((clientWidth / scrollWidth) * clientWidth, MIN_THUMB_PX)
      const range = clientWidth - size
      const offset = (scrollLeft / (scrollWidth - clientWidth)) * range
      x = { size, offset }
    }

    setMetrics({ y, x })
  }, [])

  useEffect(() => {
    measure()
    const el = viewportRef.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [measure, children])

  const handleScroll = (event) => {
    measure()
    onScroll?.(event)
  }

  // Takes `axis` as a plain argument (not curried) so JSX can wire it up via
  // a trivial forwarding arrow that touches no refs itself during render —
  // this function's body, which does read refs, only ever runs once the
  // event actually fires.
  const handlePointerDown = useCallback(
    (axis, event) => {
      event.preventDefault()
      const el = viewportRef.current
      const axisMetrics = axis === 'y' ? metrics.y : metrics.x
      if (!el || !axisMetrics) return

      const drag = {
        axis,
        startClient: axis === 'y' ? event.clientY : event.clientX,
        startScroll: axis === 'y' ? el.scrollTop : el.scrollLeft,
        trackSize: axis === 'y' ? el.clientHeight : el.clientWidth,
        thumbSize: axisMetrics.size,
        scrollRange:
          axis === 'y' ? el.scrollHeight - el.clientHeight : el.scrollWidth - el.clientWidth,
      }

      const handleMove = (moveEvent) => {
        const target = viewportRef.current
        if (!target) return
        const clientPos = drag.axis === 'y' ? moveEvent.clientY : moveEvent.clientX
        const delta = clientPos - drag.startClient
        const trackRange = drag.trackSize - drag.thumbSize
        const scrollDelta = trackRange > 0 ? (delta / trackRange) * drag.scrollRange : 0
        if (drag.axis === 'y') {
          target.scrollTop = drag.startScroll + scrollDelta
        } else {
          target.scrollLeft = drag.startScroll + scrollDelta
        }
      }

      const handleUp = () => {
        setDragging(null)
        window.removeEventListener('pointermove', handleMove)
        window.removeEventListener('pointerup', handleUp)
      }

      setDragging(axis)
      window.addEventListener('pointermove', handleMove)
      window.addEventListener('pointerup', handleUp)
    },
    [metrics],
  )

  return (
    <div className={`scroll-area ${className}`}>
      <div className="scroll-area-viewport" ref={setViewport} onScroll={handleScroll}>
        {children}
      </div>
      {metrics.y && (
        <div className="scroll-area-track-y">
          <div
            className={`scroll-area-thumb-y${dragging === 'y' ? ' dragging' : ''}`}
            style={{ height: metrics.y.size, transform: `translateY(${metrics.y.offset}px)` }}
            onPointerDown={(event) => handlePointerDown('y', event)}
          />
        </div>
      )}
      {metrics.x && (
        <div className="scroll-area-track-x">
          <div
            className={`scroll-area-thumb-x${dragging === 'x' ? ' dragging' : ''}`}
            style={{ width: metrics.x.size, transform: `translateX(${metrics.x.offset}px)` }}
            onPointerDown={(event) => handlePointerDown('x', event)}
          />
        </div>
      )}
    </div>
  )
}
