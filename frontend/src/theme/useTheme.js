import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'kpa-theme'

function readStoredTheme() {
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : null
}

function systemTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function useTheme() {
  const [theme, setTheme] = useState(() => readStoredTheme() ?? systemTheme())

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    window.localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  return { theme, isDark: theme === 'dark', setTheme, toggleTheme }
}
